from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DockerConfigTests(unittest.TestCase):
    def test_dockerfile_installs_runtime_dependencies_and_runs_entrypoint(self) -> None:
        dockerfile = (ROOT / "bot" / "Dockerfile").read_text()

        self.assertIn("ffmpeg libopus0", dockerfile)
        self.assertIn("pip install --no-cache-dir -r requirements.txt", dockerfile)
        self.assertIn('CMD ["python", "-u", "main.py"]', dockerfile)

    def test_dockerignore_excludes_runtime_data_and_python_cache(self) -> None:
        dockerignore_path = ROOT / "bot" / ".dockerignore"
        self.assertTrue(dockerignore_path.exists())
        dockerignore = dockerignore_path.read_text().splitlines()

        self.assertIn("data/", dockerignore)
        self.assertIn("__pycache__/", dockerignore)
        self.assertIn("*.py[cod]", dockerignore)

    def test_dockerignore_excludes_secret_like_files(self) -> None:
        dockerignore_path = ROOT / "bot" / ".dockerignore"
        self.assertTrue(dockerignore_path.exists())
        dockerignore = dockerignore_path.read_text().splitlines()

        self.assertIn(".env", dockerignore)
        self.assertIn(".env.*", dockerignore)
        self.assertIn("*.env", dockerignore)
        self.assertIn("*cookies*.txt", dockerignore)

    def test_compose_uses_siren_container_and_data_volume(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text()

        self.assertIn("container_name: siren-bot", compose)
        self.assertIn("./bot/data:/app/data", compose)


if __name__ == "__main__":
    unittest.main()
