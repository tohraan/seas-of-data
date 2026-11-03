# Dark at Dawn: film spec

GOAL:    A judge understands, in one watch, why ships go unseen and how Sentinel-1 radar plus a tasked buoy closes that
         gap, and believes it because the place, the radar scene and the numbers are real.
OUTPUT:  HyperFrames, 1920 x 1080, 30 fps, H.264 + AAC, `website/public/film/dark-at-dawn.mp4`.
TIME:    about 90 s = 2700 frames. The narration is the clock (SCRIPT.md, one cue per line).

LOOK:    A documentary built from real material: Blender renders of the tanker and buoy, Esri satellite imagery of
         the real coast, the real Sentinel-1D radar scene. No invented UI world around them.
         Ink #F4F1EA. Accent #FF5A36 (signal orange), only on the dark vessel and its alert. Real-data tag #7FD1C8.
         Display: Inter 600, 64 px, -1.5% tracking, for the two title moments only. Lower thirds: Inter 500, 30 px,
         over a 0.55-opacity black band that hugs the text (12 px x 20 px padding). Map labels: IBM Plex Mono 500,
         26 px, with a 2 px black text stroke so they hold over imagery.
         Footage gets a 5% vignette and 2% grain from the renders themselves; no CSS filters.
OBJECTS: The tanker (Blender A), the buoy B-07 (Blender C2) and its camera view (Blender D), the coast off Jebel Ali
         and the Gulf (satellite), Sentinel-1's ground track and 250 km swath, the radar scene with its 35 ships,
         the task message, the alert card.
MOTION:  Camera: one slow push per shot, 1.00 -> 1.06 over the shot, ease "none". Labels enter with a 12-frame
         power3.out opacity and 8 px move, hold still while read, and leave with the shot.
         Markers: a ring draws in over 10 frames (power2.out). Cuts are straight cuts; the map-to-radar change is a
         36-frame dissolve on identical pixels.
SHOTS:   see SCRIPT.md. hook (Blender A) -> gone (coast map, AIS pings, one goes silent) -> scale (zoom out to the
         Gulf, one patrol boat's view) -> orbit (globe from space to the Gulf, swath sweeps over Dubai) -> detect
         (zoom into the coast, dissolve into the radar scene, ships ring up, 8 turn orange) -> lead (push to d0190)
         -> task (d0190 and B-07 on the radar scene, message up to an IoT satellite and down) -> buoy (Blender C2)
         -> pov (Blender D, freeze to a snapshot) -> alert (card on the duty officer's screen) -> close (two lanes)
         -> end card.
SOUND:   Narration (Kokoro af_heart, local) over "Lightless Dawn" by Kevin MacLeod (CC BY 3.0) at about -26 LUFS,
         lifting for the alert. Effects are real recordings: sea and engine under the tanker, a static cut when
         the transponder goes off, a data burst for each satellite message, a motor for the camera turn, a shutter
         for the photo.
BANNED:  The defaults in the HyperFrames spec, plus: HUD corner brackets and fake readouts on the map shots,
         glowing rings, stock "scanning" lines, numbers that are not in our data or marked dramatized.
QA:      2 s disclaimer reads; 12 s one ping stops; 20 s patrol circle is tiny against the Gulf; 30 s swath over Dubai;
         38 s radar pixels line up with the map; 45 s d0190 ring; 52 s B-07 and the 3.5 km line; 60 s buoy;
         66 s snapshot; 72 s alert card; 88 s end card. Audio: voice always on top, no clipping.
