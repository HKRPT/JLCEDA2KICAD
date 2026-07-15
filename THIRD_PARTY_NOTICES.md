# Third-party notices

JLCEDA2KICAD project code is MIT licensed. The offline PCM ZIP bundles the pinned
Windows x64/Python 3.11 runtime under `plugins/vendor`; those distributions retain
their own licenses. Corresponding license files and an exact package inventory
are included under `plugins/third_party_licenses` in the ZIP. The generated
runtime payload is not committed to this source repository.

## easyeda2kicad 1.0.1

- Project: <https://github.com/uPesy/easyeda2kicad.py>
- License declared by package metadata: GNU Affero General Public License v3.0
- Use: invoked as a separate command-line process to download and convert component data.

## kicad-python 0.7.1

- Documentation: <https://docs.kicad.org/kicad-python-main/>
- Copyright: The KiCad Developers
- License shipped in the wheel: MIT
- Use: official client binding for the KiCad IPC API.
- Release tooling validates generated repository metadata with the PCM schemas
  bundled in `kicad-python==0.7.1`, under that package's licensing terms.

## PySide6 6.11.1

- Project: <https://doc.qt.io/qtforpython-6/>
- License declared by package metadata: LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only
- Use: desktop UI, asynchronous process control, SVG, and software drawing.

Consult each bundled distribution and its included license files for complete
terms and corresponding-source obligations.
