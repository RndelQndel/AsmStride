"""Verify bundled assets from the built wheel, outside the editable source tree.

Run after `npm --prefix frontend run build` and `uv build`:
    uv run --locked python tests/verify_release.py
"""

from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    wheels = list((root / 'dist').glob('armstride-*.whl'))
    assert len(wheels) == 1, 'Expected one release wheel in dist/'
    archives = list((root / 'dist').glob('armstride-*.tar.gz'))
    assert len(archives) == 1, 'Expected one release sdist in dist/'
    with tarfile.open(archives[0]) as archive:
        assert any(name.endswith('/src/armstride/static/index.html') for name in archive.getnames())
        assert any(name.endswith('/hatch_build.py') for name in archive.getnames())
    with tempfile.TemporaryDirectory() as directory:
        with zipfile.ZipFile(wheels[0]) as wheel:
            names = wheel.namelist()
            assert 'armstride/static/index.html' in names
            assert not any(name.startswith(('tests/', 'spikes/', 'frontend/')) for name in names)
            wheel.extractall(directory)
        # A fresh interpreter imports the wheel instead of the editable checkout.
        subprocess.run([sys.executable, '-c', '''
import sys
from pathlib import Path
import re
sys.path.insert(0, sys.argv[1])
from armstride.app import create_app
import armstride
from fastapi.testclient import TestClient
assert Path(armstride.__file__).is_relative_to(sys.argv[1])
with TestClient(create_app(), base_url="http://localhost") as client:
    response = client.get("/")
    assert response.status_code == 200
    assets = re.findall(r'(?:src|href)="([^\"]+\\.(?:js|css))"', response.text)
    assert len(assets) >= 2, response.text
    for asset in assets:
        result = client.get(asset)
        assert result.status_code == 200 and len(result.content) > 100
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/missing").status_code == 404
    assert client.get("/missing.js").status_code == 404
print("PASS: wheel serves packaged HTML/JS/CSS and preserves the API boundary")
''', directory], cwd=directory, check=True)
    with tempfile.TemporaryDirectory() as directory:
        with tarfile.open(archives[0]) as archive:
            archive.extractall(directory, filter='data')
        source = next(Path(directory).iterdir())
        (source / 'src/armstride/static/index.html').unlink()
        rejected = subprocess.run(['uv', 'build', '--sdist', '--offline'], cwd=source,
                                  capture_output=True, text=True)
        assert rejected.returncode != 0 and 'Build browser assets first' in rejected.stderr, rejected.stderr
    print('PASS: sdist includes release assets; missing-asset release builds fail explicitly')


if __name__ == '__main__':
    main()
