# ml/ — owner: Tohraan (ml-agent)
Ship detection on Sentinel-1 SAR: fine-tune a pretrained YOLO (ultralytics) on a public SAR ship dataset (SSDD / HRSID / xView3),
run on Gulf scenes (Jebel Ali, Khalifa Port, Strait of Hormuz), match detections to AIS (real sample or clearly-labelled simulated),
flag dark vessels, count port activity. Output ONLY the files described in `contracts/`.
Use `uv` with Python 3.12 (`uv venv --python 3.12`); Python 3.14 lacks some ML wheels. Train in Colab if no GPU.
Do not touch `dashboard/` or `cad/`.
