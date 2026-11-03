# Monitoring buoy datasheet

**Design only. Not built or tested.** These figures are calculated from the CAD model (`geometry.json`) and the assumptions below by `calc_buoy.py`. None has been measured on a real buoy.

## Headline numbers
| | |
|---|---|
| Total mass, including chain load | 532 kg |
| Waterline | 320 mm above the hull's underside, leaving 380 mm of freeboard |
| Keel ballast needed | 142 kg |
| Reserve buoyancy up to the deck | 185% of displacement |
| Metacentric height | 0.83 m |
| Heel in a 25 m/s wind | about 9° |
| Solar in the worst month | 790 Wh a day, against a 174 Wh load (4.5 times) |
| Battery with no sun | 12 days |
| AIS range, large ship | 24 km |
| AIS range, small craft | 15 km |
| Camera recognition range, 60 m ship | about 9 km, in clear air |

## Mass budget
| Item | Detail | kg | Height of centre (mm) |
|---|---|---:|---:|
| Hull shell | Polyethylene, 12 mm | 83.5 | 393 |
| Hull foam | Closed-cell, keeps it afloat if holed | 53.7 | 393 |
| Solar panels | 1.57 m2 | 18.8 | 960 |
| Battery | LiFePO4 battery, 2.56 kWh | 24.0 | 800 |
| Electronics | Processor, radios, charger, wiring | 6.0 | 1000 |
| Fender | EVA foam | 16.0 | 470 |
| ElectronicsBay | Aluminium, 5 mm wall | 22.1 | 908 |
| Hatch | Aluminium | 34.1 | 1135 |
| PanelPosts | Aluminium tube, 3 mm wall | 1.8 | 827 |
| Mast | Aluminium tube, 4 mm wall | 12.3 | 1864 |
| RadarReflector | Aluminium sheet, 3 mm | 3.9 | 2250 |
| CameraMount | Aluminium, 3 mm wall | 1.3 | 3081 |
| CameraDome | Camera and dome | 3.5 | 3130 |
| AISAntenna | Fibreglass whip and base | 1.5 | 3357 |
| OilSheenSensor | Sensor in stainless housing | 6.0 | -56 |
| SensorWindow | Sapphire window | 0.5 | -114 |
| MooringEye | Stainless steel | 18.5 | -186 |
| Mooring chain load | 25 m of chain, weight in water | 82.5 | -421 |
| Keel ballast | Set so the buoy floats at the design waterline | 141.9 | 60 |

## Floating and stability
Heights are measured from the hull's underside. KB is the centre of buoyancy, BM comes from the water-plane's shape, and KG is the centre of gravity.

GM = KB + BM - KG = 186 + 998 - 351 = 833 mm. Positive means the buoy rights itself. A wide, flat hull like this gets most of its stability from its shape.

Righting moment at 10° of heel is about 754 N·m. This small-angle method doesn't cover capsize in breaking waves, which would need a full analysis or a tank test. Without ballast, the buoy would float at 262 mm.

## Power
| Load | W | Hours a day | Wh a day |
|---|---:|---:|---:|
| AIS receiver | 1.5 | 24 | 36.0 |
| Processor | 4.0 | 24 | 96.0 |
| Satellite IoT modem, standby | 0.2 | 24 | 4.8 |
| Satellite IoT modem, sending | 5.0 | 0.5 | 2.5 |
| Camera | 8.0 | 2 | 16.0 |
| Oil-sheen sensor | 3.0 | 2.4 | 7.2 |
| Navigation light | 1.0 | 12 | 12.0 |

Solar yield = 1.57 m² x 20% efficiency x 4.0 kWh/m²/day x 0.9 for tilt and facing x 0.7 for heat, dust and salt = 790 Wh a day.

## Range
- **AIS:** radio horizon, 4.12 x (√antenna height + √other antenna height), in km and metres. The buoy's antenna tip is 3.77 m above water, with 15 m assumed for a large ship and 3 m for small craft. A real link also depends on transmit power, so this is an upper limit.
- **Camera:** 3840 pixels across 30°, needing 50 pixels along the ship to recognise it. Haze, spray and the buoy's motion will shorten this. The horizon itself limits the view of a ship's 25 m superstructure to about 24 km.

## Assumptions
These aren't measured, and changing them in `calc_buoy.py` updates everything above.

| Assumption | Value |
|---|---:|
| seawater density kg m3 | 1030 |
| target waterline mm | 320 |
| hull shell mm | 12 |
| water depth m | 25 |
| chain submerged kg per m | 3.3 |
| ballast centre z mm | 60 |
| wind speed m s | 25 |
| wind drag coefficient | 1.2 |
| air density kg m3 | 1.225 |
| panel efficiency | 0.2 |
| system derate | 0.7 |
| tilt and facing factor | 0.9 |
| worst month irradiance kwh m2 day | 4.0 |
| battery kwh | 2.56 |
| battery usable fraction | 0.8 |
| large ship antenna m | 15 |
| small craft antenna m | 3 |
| camera horizontal px | 3840 |
| camera horizontal fov deg | 30 |
| camera pixels on target to recognise | 50 |
| camera target length m | 60 |
