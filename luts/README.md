# LUTs (drop your `.cube` 3D LUTs here) — v2.1-P1-1

Any `*.cube` file in this folder becomes a one-click look in the video
review surface (`/video/<run_id>` → 🎩 grade dropdown), alongside the
built-in parametric presets (Fuji Eterna / Kodak Vision3 / Arri 709A /
Teal-Orange / B&W).

* Format: standard Adobe / DaVinci Resolve **3D** `.cube`
  (`LUT_3D_SIZE`, optional `DOMAIN_MIN`/`DOMAIN_MAX`; red varies fastest).
  1D LUTs are not supported.
* Applied with trilinear interpolation in numpy
  (`pixcull/scoring/color_grade.py::apply_cube`).
* **Preview only** — the LUT is applied to the on-screen JPEG, never to
  your originals.
* The dropdown option id is `cube:<filename-without-extension>`.

Example: drop `Kodak2383.cube` here → it shows as **"LUT · Kodak2383"**.

(Real `.cube` files are not committed — they're often licensed.  This
folder ships with just this README so the drop-in path exists.)
