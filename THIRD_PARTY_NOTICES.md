# Third-party notices

This plugin contains newly written integration, storage, transport, and tests.
Its design references the score upload flow in the following repositories.
No entire upstream plugin, song database, graphics engine, or binary is bundled.

- **maimaiDX**, copyright (c) 2021 Yuri-YuzuChaN, MIT.
  Reference: `AFKsuper/maimaiDX` commit
  `562f92b85045ef7f94f79689ddc709ab0062ef39`, especially
  `core/upload.py` and `commands/mai_upload.py`.
  Original notice and complete permission text: [licenses/maimaiDX-MIT.txt](licenses/maimaiDX-MIT.txt).
  The integration was independently implemented with separate image handling,
  Hoshino v1 routing, encrypted storage and response confirmation.
- **maimai-py 1.5.2**, Usagi no Niku. Installed as a dependency, not vendored.
  Its PyPI metadata and fork pyproject say MIT, but the actual repository and
  wheel `LICENSE` contain **Apache License 2.0**. This discrepancy is explicitly
  retained; we do not relicense upstream code. The actual distributed text is
  preserved in [licenses/maimai-py-Apache-2.0.txt](licenses/maimai-py-Apache-2.0.txt).
- **maimai-ffi 0.7.1**, copyright (c) 2024 Usagi no Niku, MIT in the distributed
  wheel. This is a compiled dependency, not an audited open-source implementation
  of the arcade protocol. Its notice is preserved in
  [licenses/maimai-ffi-MIT.txt](licenses/maimai-ffi-MIT.txt).
- **HoshinoBot**, GPL-3.0, read-only host reference
  `AFKsuper/HoshinoBot` commit `781a902a4d701162d87456bebb7254a8803a4e31`.
  The plugin imports the existing host API. No HoshinoBot source is bundled;
  the smoke script copies a user-supplied checkout only into temporary test space.
- **Diving-Fish/maimaidx-prober**, read-only server reference
  `e01075f70bb8dc1368ecbc2502a38edae525893c`.
  Used to verify the actual `update_records` success response and field updates;
  no server source is copied into this plugin.

Other runtime dependencies (aiohttp, HTTPX, cryptography, Pillow, zxing-cpp,
Tenacity, aiocache and transitive packages) retain their respective distributed
licenses and notices. Install their original wheels/sdists through pip.
The project license applies only to this project's new code.
