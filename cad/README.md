# CAD tooling

Verified on Fedora 44 on 2 Nov 2026. Both tools are per-user Flatpaks from Flathub, so neither is on PATH. Use these full commands:

| Tool | Version | Command |
|---|---|---|
| FreeCAD (headless) | 1.1.4 | `flatpak run --command=FreeCADCmd org.freecad.FreeCAD <script.py>` |
| Blender (headless) | 5.2.0 LTS | `flatpak run org.blender.Blender -b -P <script.py>` |

Install:
```bash
flatpak install --user -y flathub org.freecad.FreeCAD org.blender.Blender
```

Verify:
```bash
echo 'import FreeCAD; print("FREECAD_VERSION", ".".join(FreeCAD.Version()[:3]))' > ~/fc_version.py
flatpak run --command=FreeCADCmd org.freecad.FreeCAD ~/fc_version.py
flatpak run org.blender.Blender -b --version
```

Notes:
- Flatpak apps get a private `/tmp`, so keep scripts and outputs under your home directory.
- Flathub ships Blender 5.2, which is newer than the 4.x in the project brief.
