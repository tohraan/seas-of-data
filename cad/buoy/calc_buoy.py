"""Work out the buoy's mass, waterline, stability, power and range from the CAD geometry.

Run from the repo root, after measure_buoy.py:
  python3 cad/buoy/calc_buoy.py

Writes specs.json and DATASHEET.md. Geometry comes from the model. Every input that doesn't is named in ASSUMPTIONS and
printed on the datasheet, so anyone can see what these numbers rest on. This is a design calculation for a buoy that
hasn't been built or tested.
"""
import itertools
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRAVITY = 9.81
MM_TO_M = 0.001
PI = math.pi

ASSUMPTIONS = {
    "seawater_density_kg_m3": 1030,
    "target_waterline_mm": 320,
    "hull_shell_mm": 12,
    "water_depth_m": 25,
    "chain_submerged_kg_per_m": 3.3,
    "ballast_centre_z_mm": 60,
    "wind_speed_m_s": 25,
    "wind_drag_coefficient": 1.2,
    "air_density_kg_m3": 1.225,
    "panel_efficiency": 0.20,
    "system_derate": 0.70,
    "tilt_and_facing_factor": 0.90,
    "worst_month_irradiance_kwh_m2_day": 4.0,
    "battery_kwh": 2.56,
    "battery_usable_fraction": 0.80,
    "large_ship_antenna_m": 15,
    "small_craft_antenna_m": 3,
    "camera_horizontal_px": 3840,
    "camera_horizontal_fov_deg": 30,
    "camera_pixels_on_target_to_recognise": 50,
    "camera_target_length_m": 60,
}

DENSITY = {"polyethylene": 950, "pu_foam": 40, "eva_foam": 250, "aluminium": 2700, "stainless": 7900}

# Part name in the CAD model: (what it's made of in the mass budget, how the mass is worked out, value).
#   "shell": area x wall thickness x density.   "solid": volume x density.   "solid_scaled": solid mass x value.
#   "fixed": a catalogue-style figure in kg, at the part's centre.
MATERIALS = {
    "Fender": ("EVA foam", "solid", DENSITY["eva_foam"], None),
    "ElectronicsBay": ("Aluminium, 5 mm wall", "shell", DENSITY["aluminium"], 5),
    "Hatch": ("Aluminium", "solid", DENSITY["aluminium"], None),
    "PanelPosts": ("Aluminium tube, 3 mm wall", "shell", DENSITY["aluminium"], 3),
    "Mast": ("Aluminium tube, 4 mm wall", "shell", DENSITY["aluminium"], 4),
    "RadarReflector": ("Aluminium sheet, 3 mm", "solid_scaled", DENSITY["aluminium"], 3 / 8),
    "CameraMount": ("Aluminium, 3 mm wall", "shell", DENSITY["aluminium"], 3),
    "CameraDome": ("Camera and dome", "fixed", 3.5, None),
    "AISAntenna": ("Fibreglass whip and base", "fixed", 1.5, None),
    "OilSheenSensor": ("Sensor in stainless housing", "fixed", 6.0, None),
    "SensorWindow": ("Sapphire window", "fixed", 0.5, None),
    "MooringEye": ("Stainless steel", "solid", DENSITY["stainless"], None),
}
SOLAR_PANEL_KG_M2 = 12
SOLAR_PANEL_AREA_M2 = 4 * 0.56 * 0.70
BATTERY = ("LiFePO4 battery, 2.56 kWh", 24.0, 800)
ELECTRONICS = ("Processor, radios, charger, wiring", 6.0, 1000)

# Name: (watts, hours per day).
LOADS = {
    "AIS receiver": (1.5, 24),
    "Processor": (4.0, 24),
    "Satellite IoT modem, standby": (0.2, 24),
    "Satellite IoT modem, sending": (5.0, 0.5),
    "Camera": (8.0, 2),
    "Oil-sheen sensor": (3.0, 2.4),
    "Navigation light": (1.0, 12),
}
# Side-on area in m2 and height of its centre above the hull's underside in mm: rough shapes for the wind estimate.
WINDAGE = [
    ("Hull above water", 1.8 * 0.38, 510),
    ("Solar panels", 2 * 0.70 * 0.56 * math.sin(math.radians(25)) + 0.70 * 0.035, 960),
    ("Electronics bay", 0.68 * 0.45, 925),
    ("Mast and struts", 0.09 * 1.9 + 4 * 0.036 * 1.3, 2100),
    ("Radar reflector", PI * 0.23**2, 2250),
]


def radio_horizon_km(height_a_m: float, height_b_m: float) -> float:
    """VHF radio horizon over the sea, using the standard 4/3 earth approximation."""
    return 4.12 * (math.sqrt(height_a_m) + math.sqrt(height_b_m))


def optical_horizon_km(height_a_m: float, height_b_m: float) -> float:
    return 3.57 * (math.sqrt(height_a_m) + math.sqrt(height_b_m))


def interpolate(curve: list[dict], z_mm: float, key: str) -> float:
    for lower, upper in itertools.pairwise(curve):
        if lower["z_mm"] <= z_mm <= upper["z_mm"]:
            fraction = (z_mm - lower["z_mm"]) / (upper["z_mm"] - lower["z_mm"])
            return lower[key] + fraction * (upper[key] - lower[key])
    raise ValueError(f"waterline {z_mm} mm is outside the measured range")


def waterline_for_volume(curve: list[dict], volume_mm3: float) -> float:
    for lower, upper in itertools.pairwise(curve):
        if lower["volume_mm3"] <= volume_mm3 <= upper["volume_mm3"]:
            fraction = (volume_mm3 - lower["volume_mm3"]) / (upper["volume_mm3"] - lower["volume_mm3"])
            return lower["z_mm"] + fraction * (upper["z_mm"] - lower["z_mm"])
    raise ValueError("this mass doesn't float inside the measured range")


def part_mass(part: dict, rule: tuple) -> float:
    _, method, value, extra = rule
    if method == "fixed":
        return value
    if method == "solid":
        return part["volume_mm3"] * 1e-9 * value
    if method == "solid_scaled":
        return part["volume_mm3"] * 1e-9 * value * extra
    if method == "shell":
        return part["area_mm2"] * 1e-6 * extra * MM_TO_M * value
    raise ValueError(method)


def mass_budget(geometry: dict, assumptions: dict) -> list[dict]:
    parts = geometry["parts"]
    hull = parts["Hull"]
    shell_volume = hull["area_mm2"] * assumptions["hull_shell_mm"]
    rows = [
        {"item": "Hull shell", "detail": f"Polyethylene, {assumptions['hull_shell_mm']} mm", "kg": shell_volume * 1e-9 * DENSITY["polyethylene"], "z_mm": hull["centre_z_mm"]},
        {"item": "Hull foam", "detail": "Closed-cell, keeps it afloat if holed", "kg": (hull["volume_mm3"] - shell_volume) * 1e-9 * DENSITY["pu_foam"], "z_mm": hull["centre_z_mm"]},
        {"item": "Solar panels", "detail": f"{SOLAR_PANEL_AREA_M2:.2f} m2", "kg": SOLAR_PANEL_AREA_M2 * SOLAR_PANEL_KG_M2, "z_mm": parts["SolarPanels"]["centre_z_mm"]},
        {"item": "Battery", "detail": BATTERY[0], "kg": BATTERY[1], "z_mm": BATTERY[2]},
        {"item": "Electronics", "detail": ELECTRONICS[0], "kg": ELECTRONICS[1], "z_mm": ELECTRONICS[2]},
    ]
    for name, rule in MATERIALS.items():
        rows.append({"item": name, "detail": rule[0], "kg": part_mass(parts[name], rule), "z_mm": parts[name]["centre_z_mm"]})
    return rows


def calculate(geometry: dict, assumptions: dict = ASSUMPTIONS) -> dict:
    curve = geometry["displacement_curve"]
    density = assumptions["seawater_density_kg_m3"]
    waterline = assumptions["target_waterline_mm"]

    rows = mass_budget(geometry, assumptions)
    eye_z = geometry["parts"]["MooringEye"]["z_min_mm"]
    chain_kg = assumptions["water_depth_m"] * assumptions["chain_submerged_kg_per_m"]
    rows.append({"item": "Mooring chain load", "detail": f"{assumptions['water_depth_m']} m of chain, weight in water", "kg": chain_kg, "z_mm": eye_z})

    volume_mm3 = interpolate(curve, waterline, "volume_mm3")
    displacement_kg = volume_mm3 * 1e-9 * density
    carried_kg = sum(row["kg"] for row in rows)
    ballast_kg = displacement_kg - carried_kg
    if ballast_kg < 0:
        raise ValueError(f"the buoy is {-ballast_kg:.0f} kg too heavy for a {waterline} mm waterline")
    rows.append({"item": "Keel ballast", "detail": "Set so the buoy floats at the design waterline", "kg": ballast_kg, "z_mm": assumptions["ballast_centre_z_mm"]})

    # Stability, measured from the hull's underside.
    kg_mm = sum(row["kg"] * row["z_mm"] for row in rows) / displacement_kg
    kb_mm = interpolate(curve, waterline, "centre_z_mm")
    waterplane_mm2 = interpolate(curve, waterline, "waterplane_area_mm2")
    radius_mm = math.sqrt(waterplane_mm2 / PI)
    inertia_mm4 = PI * radius_mm**4 / 4
    bm_mm = inertia_mm4 / volume_mm3
    gm_mm = kb_mm + bm_mm - kg_mm
    if gm_mm <= 0:
        raise ValueError("the buoy is unstable at this loading")
    stiffness_nm_per_rad = displacement_kg * GRAVITY * gm_mm * MM_TO_M

    # Wind heel.
    wind_force = 0.0
    wind_moment = 0.0
    for _, area_m2, height_mm in WINDAGE:
        force = 0.5 * assumptions["air_density_kg_m3"] * assumptions["wind_drag_coefficient"] * area_m2 * assumptions["wind_speed_m_s"] ** 2
        wind_force += force
        wind_moment += force * (height_mm - waterline) * MM_TO_M
    heel_deg = math.degrees(math.atan(wind_moment / stiffness_nm_per_rad))

    # Reserve buoyancy up to the deck. The hull's foam fill keeps this even if the shell is holed.
    hull_top = geometry["parts"]["Hull"]["z_max_mm"]
    deck_volume_mm3 = interpolate(curve, hull_top - 1, "volume_mm3")
    no_ballast_waterline = waterline_for_volume(curve, carried_kg / density * 1e9)

    # Power.
    daily_load_wh = sum(watts * hours for watts, hours in LOADS.values())
    daily_yield_wh = (
        SOLAR_PANEL_AREA_M2 * assumptions["panel_efficiency"] * assumptions["worst_month_irradiance_kwh_m2_day"]
        * assumptions["tilt_and_facing_factor"] * assumptions["system_derate"] * 1000
    )
    usable_battery_wh = assumptions["battery_kwh"] * assumptions["battery_usable_fraction"] * 1000
    autonomy_days = usable_battery_wh / daily_load_wh

    # Range.
    antenna_m = (geometry["z_top_mm"] - waterline) * MM_TO_M
    dome = geometry["parts"]["CameraDome"]
    camera_m = (dome["centre_z_mm"] - waterline) * MM_TO_M
    pixel_rad = math.radians(assumptions["camera_horizontal_fov_deg"]) / assumptions["camera_horizontal_px"]
    recognise_km = assumptions["camera_target_length_m"] / (assumptions["camera_pixels_on_target_to_recognise"] * pixel_rad) / 1000

    return {
        "status": "Design only. Not built or tested.",
        "mass_budget": [{**row, "kg": round(row["kg"], 1), "z_mm": round(row["z_mm"])} for row in rows],
        "total_mass_kg": round(displacement_kg, 1),
        "mass_without_chain_kg": round(displacement_kg - chain_kg, 1),
        "keel_ballast_kg": round(ballast_kg, 1),
        "waterline_mm": waterline,
        "freeboard_mm": round(hull_top - waterline),
        "displaced_volume_m3": round(volume_mm3 * 1e-9, 3),
        "waterline_without_ballast_mm": round(no_ballast_waterline),
        "reserve_buoyancy_percent": round(100 * (deck_volume_mm3 - volume_mm3) / volume_mm3),
        "kg_mm": round(kg_mm),
        "kb_mm": round(kb_mm),
        "bm_mm": round(bm_mm),
        "metacentric_height_m": round(gm_mm * MM_TO_M, 2),
        "righting_moment_at_10_deg_nm": round(displacement_kg * GRAVITY * gm_mm * MM_TO_M * math.sin(math.radians(10))),
        "wind_heel_deg": round(heel_deg, 1),
        "wind_speed_m_s": assumptions["wind_speed_m_s"],
        "solar_area_m2": round(SOLAR_PANEL_AREA_M2, 2),
        "daily_solar_wh_worst_month": round(daily_yield_wh),
        "daily_load_wh": round(daily_load_wh),
        "power_margin": round(daily_yield_wh / daily_load_wh, 1),
        "battery_autonomy_days": round(autonomy_days, 1),
        "loads": {name: {"watts": watts, "hours_per_day": hours, "wh_per_day": round(watts * hours, 1)} for name, (watts, hours) in LOADS.items()},
        "ais_antenna_above_water_m": round(antenna_m, 2),
        "ais_range_large_ship_km": round(radio_horizon_km(antenna_m, assumptions["large_ship_antenna_m"]), 1),
        "ais_range_small_craft_km": round(radio_horizon_km(antenna_m, assumptions["small_craft_antenna_m"]), 1),
        "camera_above_water_m": round(camera_m, 2),
        "camera_recognition_range_km": round(recognise_km, 1),
        "camera_horizon_to_25m_ship_km": round(optical_horizon_km(camera_m, 25), 1),
        "assumptions": assumptions,
    }


def datasheet(specs: dict) -> str:
    assumptions = specs["assumptions"]
    budget = "\n".join(f"| {row['item']} | {row['detail']} | {row['kg']:.1f} | {row['z_mm']} |" for row in specs["mass_budget"])
    loads = "\n".join(f"| {name} | {load['watts']} | {load['hours_per_day']} | {load['wh_per_day']} |" for name, load in specs["loads"].items())
    return f"""# Monitoring buoy datasheet

**{specs['status']}** These figures are calculated from the CAD model (`geometry.json`) and the assumptions below by `calc_buoy.py`. None has been measured on a real buoy.

## Headline numbers
| | |
|---|---|
| Total mass, including chain load | {specs['total_mass_kg']:.0f} kg |
| Waterline | {specs['waterline_mm']} mm above the hull's underside, leaving {specs['freeboard_mm']} mm of freeboard |
| Keel ballast needed | {specs['keel_ballast_kg']:.0f} kg |
| Reserve buoyancy up to the deck | {specs['reserve_buoyancy_percent']}% of displacement |
| Metacentric height | {specs['metacentric_height_m']:.2f} m |
| Heel in a {specs['wind_speed_m_s']} m/s wind | about {specs['wind_heel_deg']:.0f}° |
| Solar in the worst month | {specs['daily_solar_wh_worst_month']} Wh a day, against a {specs['daily_load_wh']} Wh load ({specs['power_margin']:.1f} times) |
| Battery with no sun | {specs['battery_autonomy_days']:.0f} days |
| AIS range, large ship | {specs['ais_range_large_ship_km']:.0f} km |
| AIS range, small craft | {specs['ais_range_small_craft_km']:.0f} km |
| Camera recognition range, {assumptions['camera_target_length_m']} m ship | about {specs['camera_recognition_range_km']:.0f} km, in clear air |

## Mass budget
| Item | Detail | kg | Height of centre (mm) |
|---|---|---:|---:|
{budget}

## Floating and stability
Heights are measured from the hull's underside. KB is the centre of buoyancy, BM comes from the water-plane's shape, and KG is the centre of gravity.

GM = KB + BM - KG = {specs['kb_mm']} + {specs['bm_mm']} - {specs['kg_mm']} = {specs['kb_mm'] + specs['bm_mm'] - specs['kg_mm']} mm. Positive means the buoy rights itself. A wide, flat hull like this gets most of its stability from its shape.

Righting moment at 10° of heel is about {specs['righting_moment_at_10_deg_nm']} N·m. This small-angle method doesn't cover capsize in breaking waves, which would need a full analysis or a tank test. Without ballast, the buoy would float at {specs['waterline_without_ballast_mm']} mm.

## Power
| Load | W | Hours a day | Wh a day |
|---|---:|---:|---:|
{loads}

Solar yield = {specs['solar_area_m2']} m² x {assumptions['panel_efficiency']:.0%} efficiency x {assumptions['worst_month_irradiance_kwh_m2_day']} kWh/m²/day x {assumptions['tilt_and_facing_factor']} for tilt and facing x {assumptions['system_derate']} for heat, dust and salt = {specs['daily_solar_wh_worst_month']} Wh a day.

## Range
- **AIS:** radio horizon, 4.12 x (√antenna height + √other antenna height), in km and metres. The buoy's antenna tip is {specs['ais_antenna_above_water_m']} m above water, with {assumptions['large_ship_antenna_m']} m assumed for a large ship and {assumptions['small_craft_antenna_m']} m for small craft. A real link also depends on transmit power, so this is an upper limit.
- **Camera:** {assumptions['camera_horizontal_px']} pixels across {assumptions['camera_horizontal_fov_deg']}°, needing {assumptions['camera_pixels_on_target_to_recognise']} pixels along the ship to recognise it. Haze, spray and the buoy's motion will shorten this. The horizon itself limits the view of a ship's 25 m superstructure to about {specs['camera_horizon_to_25m_ship_km']:.0f} km.

## Assumptions
These aren't measured, and changing them in `calc_buoy.py` updates everything above.

| Assumption | Value |
|---|---:|
""" + "\n".join(f"| {key.replace('_', ' ')} | {value} |" for key, value in assumptions.items()) + "\n"


def main() -> None:
    geometry = json.loads((HERE / "geometry.json").read_text())
    specs = calculate(geometry)
    (HERE / "specs.json").write_text(json.dumps(specs, indent=1) + "\n")
    (HERE / "DATASHEET.md").write_text(datasheet(specs))
    for key in (
        "total_mass_kg", "keel_ballast_kg", "waterline_without_ballast_mm", "freeboard_mm", "reserve_buoyancy_percent", "kb_mm", "bm_mm", "kg_mm",
        "metacentric_height_m", "wind_heel_deg", "daily_solar_wh_worst_month", "daily_load_wh", "power_margin", "battery_autonomy_days",
        "ais_antenna_above_water_m", "ais_range_large_ship_km", "ais_range_small_craft_km", "camera_above_water_m", "camera_recognition_range_km",
    ):
        print(f"{key}: {specs[key]}")


if __name__ == "__main__":
    main()
