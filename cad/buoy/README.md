# Monitoring buoy

A floating, solar-powered buoy that checks satellite ship detections on site. Sentinel-1 radar covers a wide area but only at each pass. The buoy watches one spot of interest all the time.

This is a design only: it hasn't been built or tested. The numbers below are calculated from the CAD model and stated assumptions, and [DATASHEET.md](DATASHEET.md) shows the working. No structural or mooring analysis has been done.

## Files
| File | Use |
|---|---|
| `buoy.step` | Main CAD file to submit, with each part as a named solid |
| `buoy.FCStd` | FreeCAD document |
| `buoy.stl` | Whole buoy as one watertight mesh |
| `parts/*.stl` | One mesh per part, used for the renders |
| `build_buoy.py` | Generates all of the above |
| `geometry.json`, `measure_buoy.py` | Volumes, areas and heights measured from the model |
| `specs.json`, `DATASHEET.md`, `calc_buoy.py` | The calculated numbers and their assumptions |
| `../render_buoy.py` | Renders the images in `../renders/`: `hero`, `side`, `top` and `closeup`, plus 1920 px `deck_hero` and `deck_masthead` for slides |

## Rebuild
Run from the repo root. Dimensions are named constants at the top of `build_buoy.py`.
```bash
flatpak run --command=FreeCADCmd org.freecad.FreeCAD cad/buoy/build_buoy.py
flatpak run org.blender.Blender -b -P "$PWD/cad/render_buoy.py"
flatpak run --command=FreeCADCmd org.freecad.FreeCAD cad/buoy/measure_buoy.py
python3 cad/buoy/calc_buoy.py
```

The build stops with an error if a part is invalid, a part isn't connected to the rest, or the STL isn't watertight. The calculation stops with an error if the buoy is too heavy for its waterline or unstable.

## Size and calculated numbers
- **Hull:** 1.8 m diameter, 0.7 m high.
- **Overall height:** about 4.5 m, from the mooring eye to the antenna tip.

| | |
|---|---|
| Total mass, including chain load | 532 kg, with 142 kg of keel ballast |
| Waterline | 320 mm above the hull's underside, with 380 mm of freeboard |
| Stability | Metacentric height 0.83 m, about 9° of heel in a 25 m/s wind |
| Power | 790 Wh a day of solar in the worst month, against a 174 Wh load, and 12 days on battery |
| AIS range | About 24 km for large ships and 15 km for small craft, at most |
| Camera range | About 9 km to recognise a 60 m ship, in clear air |

## Parts
| Part | Purpose |
|---|---|
| Hull | Provides buoyancy. Yellow is the standard colour for special-purpose marks at sea. |
| Fender | Rubber ring that protects the hull from knocks by small craft. |
| Electronics bay and hatch | Sealed space for the batteries, processor and radio link, with a bolted hatch for servicing. |
| Solar panels (4) | Power everything. They face four directions and tilt outward to shed water and spray. |
| Mast and struts | Lift the sensors above spray and wave height. |
| AIS antenna | Receives the identity and position messages that ships broadcast. |
| Radar reflector | Three crossed discs that make the buoy easy for ships' radar to see from any direction. |
| Camera | Dome camera at the top of the mast, for visual confirmation of nearby vessels. |
| Oil-sheen sensor | Sits under the hull behind a protective ring, offset from the centre to keep clear of the mooring chain. Its role is to flag possible oil in the water around the buoy. |
| Mooring eye | Attachment point for the anchor chain, on the centre line. |

## How it complements the satellite
1. **Detect:** Sentinel-1 radar finds ships across a wide area, day or night and through cloud, but only when it passes over.
2. **Compare:** a ship seen on radar with no matching AIS message is flagged as a possible dark vessel.
3. **Verify:** near the buoy, its AIS receiver gives a local AIS record and its camera can give visual evidence, including between satellite passes.
4. **Add context:** the oil-sheen sensor adds a water-quality signal that this radar pipeline doesn't produce.

The prototype dashboard currently uses simulated AIS. A deployed buoy would be one source of real local AIS data.
