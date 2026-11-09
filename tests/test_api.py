"""
Tests unitaires pour l'application GetMyPartition.

Tous les appels aux services externes (Songsterr, MongoDB Atlas, Supabase Storage,
requêtes réseau sortantes urllib) sont bouchonnés (mockés) pour garantir des tests :
  - Déterministes (aucun besoin de réseau ni de clés API)
  - Ultra-rapides (< 1 seconde)
  - Isolés (aucun impact sur les données réelles)

Exécution :
  python3 -m unittest discover -s tests
  # ou si pytest est installé :
  pytest tests/
"""

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Assurer que la racine du projet est dans le sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app


class BaseTestCase(unittest.TestCase):
    """Classe de base configurant le client de test Flask et un dossier temporaire."""

    def setUp(self):
        app.app.config["TESTING"] = True
        self.client = app.app.test_client()

        # Dossier de téléchargement temporaire isolé pour les tests
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_partitions_dir = app.PARTITIONS_DIR
        app.PARTITIONS_DIR = Path(self.temp_dir.name)

    def tearDown(self):
        app.PARTITIONS_DIR = self.original_partitions_dir
        self.temp_dir.cleanup()


class TestStaticRoutes(BaseTestCase):
    """Vérification des routes statiques et PWA."""

    def test_index_route(self):
        """GET / doit renvoyer l'interface index.html."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"GetMyPartition", response.data)

    def test_service_worker_headers(self):
        """GET /sw.js doit retourner du JavaScript avec les en-têtes PWA spécifiques."""
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/javascript", response.headers.get("Content-Type", ""))
        self.assertEqual(response.headers.get("Service-Worker-Allowed"), "/")

    def test_manifest_headers(self):
        """GET /manifest.json doit retourner le JSON avec le MIME officiel PWA."""
        response = self.client.get("/manifest.json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/manifest+json", response.headers.get("Content-Type", ""))
        data = response.get_json()
        self.assertIsNotNone(data)
        self.assertIn("icons", data)

    def test_healthcheck(self):
        """GET /api/healthcheck doit renvoyer 200 OK pour le monitoring."""
        response = self.client.get("/api/healthcheck")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "OK")


class TestRecentSearchesAPI(BaseTestCase):
    """Tests pour l'endpoint /api/recent-searches avec bouchon MongoDB."""

    def test_recent_searches_with_mock_db(self):
        """Vérifie la restitution des recherches avec bouchon MongoDB."""
        fake_searches = [
            {"artist": "Nirvana", "title": "Smells Like Teen Spirit", "display": "Nirvana - Smells Like Teen Spirit"},
            {"artist": "The Offspring", "title": "The Kids Aren't Alright", "display": "The Offspring - The Kids Aren't Alright"},
        ]

        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.limit.return_value = fake_searches
        mock_cursor.__iter__.return_value = iter(fake_searches)

        mock_collection = MagicMock()
        mock_collection.find.return_value = mock_cursor

        with patch.object(app, "mongo_search_collection", mock_collection):
            response = self.client.get("/api/recent-searches")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(len(data.get("searches")), 2)
            self.assertEqual(data["searches"][0]["artist"], "Nirvana")

    def test_recent_searches_when_no_db(self):
        """Si MongoDB n'est pas initialisé, doit renvoyer une liste vide sans planter."""
        with patch.object(app, "mongo_search_collection", None):
            response = self.client.get("/api/recent-searches")
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("searches"), [])


class TestSearchAPI(BaseTestCase):
    """Tests de recherche multi-sources (/api/search)."""

    def test_search_missing_parameters(self):
        """Une recherche vide sans terme doit renvoyer 400 Bad Request."""
        response = self.client.get("/api/search")
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertFalse(data.get("success"))

    @patch("sources.songsterr.search_songs")
    @patch("sources.myguitarpro.search_songs")
    def test_search_nominal(self, mock_mygppro_search, mock_songsterr_search):
        """Recherche nominale avec bouchons sur les sources externes."""
        mock_songsterr_search.return_value = [
            {"songId": 123, "artist": "Metallica", "title": "Enter Sandman"}
        ]
        mock_mygppro_search.return_value = [
            {"songId": "track_456.gp5", "artist": "Metallica", "title": "Master of Puppets"}
        ]

        response = self.client.get("/api/search?q=metallica")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("query"), "metallica")
        self.assertEqual(len(data.get("groups")), 2)

        # Vérifier que les résultats de chaque source sont bien présents
        group_sources = {g["source_id"]: g["results"] for g in data["groups"]}
        self.assertEqual(len(group_sources["songsterr"]), 1)
        self.assertEqual(group_sources["songsterr"][0]["title"], "Enter Sandman")
        self.assertEqual(len(group_sources["mygppro"]), 1)
        self.assertEqual(group_sources["mygppro"][0]["title"], "Master of Puppets")

    @patch("sources.songsterr.search_songs")
    @patch("sources.myguitarpro.search_songs")
    def test_search_partial_failure_resilience(self, mock_mygppro_search, mock_songsterr_search):
        """Si une source lève une erreur, l'autre source continue et l'API ne plante pas."""
        mock_songsterr_search.side_effect = RuntimeError("Songsterr API Down")
        mock_mygppro_search.return_value = [
            {"songId": "local_track.gp5", "artist": "Queen", "title": "Bohemian Rhapsody"}
        ]

        response = self.client.get("/api/search?q=queen")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))

        group_map = {g["source_id"]: g for g in data["groups"]}
        self.assertIsNotNone(group_map["songsterr"]["error"])
        self.assertEqual(len(group_map["songsterr"]["results"]), 0)
        self.assertIsNone(group_map["mygppro"]["error"])
        self.assertEqual(len(group_map["mygppro"]["results"]), 1)


class TestSongAndCheckAPI(BaseTestCase):
    """Tests des endpoints /api/song et /api/check."""

    def test_song_missing_id(self):
        """ID manquant -> 400."""
        response = self.client.get("/api/song")
        self.assertEqual(response.status_code, 400)

    def test_song_unknown_source(self):
        """Source inconnue -> 400."""
        response = self.client.get("/api/song?id=123&source=source_inconnue")
        self.assertEqual(response.status_code, 400)

    @patch("sources.songsterr.get_song_gp_source")
    def test_song_details_nominal(self, mock_get_source):
        """Récupération réussie des détails d'un morceau Songsterr bouchonné."""
        mock_get_source.return_value = {
            "song_id": 325,
            "artist": "The Offspring",
            "title": "The Kids Aren't Alright",
            "source_url": "https://gp.songsterr.com/export.920770880.gp",
            "tracks": [{"index": 0, "name": "Guitar"}]
        }

        response = self.client.get("/api/song?id=325&source=songsterr")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data["details"]["artist"], "The Offspring")

    @patch("sources.songsterr.get_song_gp_source")
    def test_check_available(self, mock_get_source):
        """Vérification de disponibilité avec succès."""
        mock_get_source.return_value = {
            "source_url": "https://gp.songsterr.com/sample.gp"
        }
        response = self.client.get("/api/check?id=123&source=songsterr")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("available"))

    @patch("sources.songsterr.get_song_gp_source")
    def test_check_unavailable(self, mock_get_source):
        """Vérification de disponibilité quand aucune tablature binaire n'existe."""
        mock_get_source.side_effect = ValueError("Aucune tablature binaire")
        response = self.client.get("/api/check?id=123&source=songsterr")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data.get("available"))


class TestDownloadAndSecurityAPI(BaseTestCase):
    """Tests des endpoints de téléchargement et validations de sécurité (SSRF, Path Traversal)."""

    @patch("sources.songsterr.get_song_gp_source")
    @patch("sources.songsterr.download_gp_file")
    def test_download_post_nominal(self, mock_download, mock_get_source):
        """POST /api/download télécharge le fichier via la source bouchonnée."""
        mock_get_source.return_value = {
            "artist": "Green Day",
            "title": "Basket Case",
            "source_url": "https://gp.songsterr.com/basket_case.gp5",
        }

        # Simuler la création du fichier par download_gp_file
        def fake_download(url, path):
            Path(path).write_bytes(b"FICHIER_GP_TEST")
            return Path(path)
        mock_download.side_effect = fake_download

        response = self.client.post("/api/download", json={"id": "456", "source": "songsterr"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        self.assertIn("Basket_Case", data.get("filename"))

    @patch("sources.songsterr.get_song_gp_source")
    def test_download_ssrf_blocked_on_unauthorized_host(self, mock_get_source):
        """Une URL non autorisée (tentative SSRF vers IP privée ou serveur tiers) doit être bloquée avec 403."""
        mock_get_source.return_value = {
            "artist": "Hacker",
            "title": "Exploit",
            "source_url": "http://127.0.0.1:8080/admin/secrets",
        }

        response = self.client.post("/api/download", json={"id": "999", "source": "songsterr"})
        self.assertEqual(response.status_code, 403)
        data = response.get_json()
        self.assertFalse(data.get("success"))
        self.assertIn("non autorisée", data.get("error"))

    @patch("sources.myguitarpro.get_song_gp_source")
    @patch("sources.myguitarpro.download_gp_file")
    def test_download_supabase_authorized(self, mock_download, mock_get_source):
        """Les URL signées Supabase (*.supabase.co) doivent être autorisées par la validation SSRF."""
        mock_get_source.return_value = {
            "artist": "Queen",
            "title": "Radio Ga Ga",
            "source_url": "https://qwgqkhpgekgkbvkwuaqh.supabase.co/storage/v1/object/sign/bucket/song.gp4?token=fake",
        }

        def fake_download(url, path):
            Path(path).write_bytes(b"CONTENU_SUPABASE")
            return Path(path)
        mock_download.side_effect = fake_download

        response = self.client.post("/api/download", json={"id": "song.gp4", "source": "mygppro"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))

    def test_local_files_nominal(self):
        """GET /api/local-files liste bien les fichiers .gp* présents dans PARTITIONS_DIR."""
        (app.PARTITIONS_DIR / "test1.gp5").write_bytes(b"data1")
        (app.PARTITIONS_DIR / "test2.gp").write_bytes(b"data2")
        (app.PARTITIONS_DIR / "ignore_me.txt").write_bytes(b"texte")

        response = self.client.get("/api/local-files")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        file_names = [f["name"] for f in data.get("files")]
        self.assertIn("test1.gp5", file_names)
        self.assertIn("test2.gp", file_names)
        self.assertNotIn("ignore_me.txt", file_names)

    def test_local_download_nominal(self):
        """GET /api/local-download télécharge un fichier existant dans PARTITIONS_DIR."""
        test_file = app.PARTITIONS_DIR / "solo.gp4"
        test_file.write_bytes(b"BINAIRE_SOLO")

        response = self.client.get("/api/local-download?file=solo.gp4")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"BINAIRE_SOLO")

    def test_local_download_path_traversal_blocked(self):
        """Tentative de path traversal (/api/local-download?file=../../etc/passwd) doit être bloquée avec 404."""
        response = self.client.get("/api/local-download?file=../../etc/passwd")
        self.assertEqual(response.status_code, 404)

    def test_tab_file_local_path_traversal_blocked(self):
        """Tentative de path traversal sur /api/tab-file (source=local) doit retourner 404."""
        response = self.client.get("/api/tab-file?source=local&file=../../../../etc/shadow")
        self.assertEqual(response.status_code, 404)

    @patch("sources.myguitarpro.get_file_bytes")
    def test_tab_file_mygppro_nominal(self, mock_get_bytes):
        """GET /api/tab-file pour mygppro sert le binaire issu de Supabase SDK."""
        mock_get_bytes.return_value = (b"OCTETS_GUITARPRO", "mon_morceau.gp5")

        response = self.client.get("/api/tab-file?source=mygppro&id=mon_morceau.gp5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"OCTETS_GUITARPRO")
        self.assertEqual(response.headers.get("Content-Type"), "application/octet-stream")

    @patch("sources.songsterr.get_song_gp_source")
    @patch("urllib.request.urlopen")
    def test_tab_file_songsterr_nominal(self, mock_urlopen, mock_get_source):
        """GET /api/tab-file pour songsterr sert le binaire téléchargé depuis gp.songsterr.com."""
        mock_get_source.return_value = {
            "artist": "ACDC",
            "title": "Back In Black",
            "source_url": "https://gp.songsterr.com/export.12345.gp",
        }

        # Bouchonner urllib.request.urlopen
        mock_response = MagicMock()
        mock_response.read.return_value = b"BINARY_ACDC_TAB"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        response = self.client.get("/api/tab-file?source=songsterr&id=789")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"BINARY_ACDC_TAB")

    @patch("sources.songsterr.get_song_gp_source")
    def test_tab_file_songsterr_ssrf_blocked(self, mock_get_source):
        """GET /api/tab-file avec une URL non autorisée doit être bloqué avec 403."""
        mock_get_source.return_value = {
            "artist": "Bad",
            "title": "Actor",
            "source_url": "http://169.254.169.254/latest/meta-data/",
        }

        response = self.client.get("/api/tab-file?source=songsterr&id=789")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
