# TheMidnightOperaData
Data storage for The Midnight Opera.
Used to automatically generate atlas for image-loading ingame.


---

## Default behavior

* Each folder → one atlas
* Up to **16× 512×512** images per 2048×2048 canvas (4×4 grid)
* Missing images use `placeholder.png`
* Output: `atlases/atlas_<name>.png` and `.json`

---

## Optional config.json
**Simple grid (recommended)**

```json
{ "cols": 4, "rows": 4, "slot_width": 512, "slot_height": 512 }
```

**Custom layout (advanced)**

```json
{
  "canvas_width": 1024,
  "canvas_height": 512,
  "slots": [
    {"index":1,"x":0,"y":0,"w":512,"h":512},
    {"index":2,"x":512,"y":0,"w":512,"h":512}
  ]
}
```

---

## Validation rules
* only .png
* Max canvas: 2048×2048
* No duplicate indices
* No path characters (`/`, `\\`, `..`)
* Slots must fit inside canvas

---
## Running locally

```bash
pip install Pillow
python tools/build_atlases.py
```

---

## CI / GitHub Actions

* Runs automatically on push to `atlases_src/**`
* Commits updated atlases back to repo

---
