"""Verify a release ZIP and refresh the tracked default 80 MHz downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

IMAGES = ('freeeeg32-factory.hex', 'freeeeg32-application.uf2',
          'freeeeg32-application.hex', 'freeeeg32-bootloader.hex')
DOWNLOADS = ('freeeeg32-factory.hex', 'freeeeg32-application.uf2',
             'freeeeg32-uf2-release.zip', 'manifest.json')


def sync_bundle(bundle, destination):
    bundle = Path(bundle)
    data = bundle.read_bytes()
    with zipfile.ZipFile(bundle) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError('Duplicate release ZIP members')
        if archive.testzip() is not None:
            raise ValueError('Release ZIP checksum failure')
        manifest_bytes = archive.read('manifest.json')
        manifest = json.loads(manifest_bytes)
        if manifest.get('board') != 'FreeEEG32-beta STM32H743ZI':
            raise ValueError('Release is for another board')
        if manifest.get('application_clocks', {}).get('cpu_mhz') != 80:
            raise ValueError('Precompiled downloads must use the default 80 MHz profile')
        if set(manifest.get('files', {})) != set(IMAGES):
            raise ValueError('Release manifest has unexpected image names')
        contents = {}
        for name in IMAGES:
            content = archive.read(name)
            info = manifest['files'][name]
            if len(content) != info['bytes'] or hashlib.sha256(content).hexdigest() != info['sha256']:
                raise ValueError('Release image hash/size mismatch: ' + name)
            contents[name] = content
    # Validate the complete package before replacing any tracked downloads.
    downloads = {name: contents[name] for name in DOWNLOADS if name in contents}
    downloads['freeeeg32-uf2-release.zip'] = data
    downloads['manifest.json'] = manifest_bytes
    checksums = ''.join(hashlib.sha256(downloads[name]).hexdigest() + '  ' + name + '\n'
                        for name in DOWNLOADS)
    downloads['SHA256SUMS.txt'] = checksums.encode('utf-8')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in downloads.items():
        (destination / name).write_bytes(content)
    print('Updated default 80 MHz downloads:', destination)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--destination', default=Path(__file__).resolve().parents[2] / 'Precompiled', type=Path)
    args = parser.parse_args()
    sync_bundle(args.bundle, args.destination)
