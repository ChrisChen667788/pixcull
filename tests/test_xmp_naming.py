"""Sidecar naming: Lightroom says `A.xmp`, darktable says `A.ARW.xmp`.

darktable reads a Lightroom-style sidecar on import, then writes its own
`<name>.<ext>.xmp` next to it, so a shoot ends up with two files that
drift apart. `naming="darktable"` writes and updates that one instead —
in place, because a darktable sidecar carries the develop history and
rewriting the packet would throw it away.
"""

from __future__ import annotations

from pathlib import Path

from pixcull.io.xmp import write_xmp

_HISTORY = (
    '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    '  <rdf:Description rdf:about=""\n'
    '    xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
    '    xmlns:darktable="http://darktable.sf.net/"\n'
    '    xmp:Rating="0">\n'
    '   <darktable:history>\n'
    '    <rdf:Seq><rdf:li>exposure 1.20</rdf:li></rdf:Seq>\n'
    '   </darktable:history>\n'
    '  </rdf:Description>\n'
    ' </rdf:RDF>\n'
    '</x:xmpmeta>\n'
)


def _image(tmp_path: Path, name: str = "A.ARW") -> Path:
    p = tmp_path / name
    p.write_bytes(b"raw")
    return p


def test_lightroom_naming_is_unchanged(tmp_path):
    out = write_xmp(_image(tmp_path), 5, "Green")
    assert out.name == "A.xmp"


def test_darktable_naming_uses_the_full_filename(tmp_path):
    out = write_xmp(_image(tmp_path), 5, "Green", naming="darktable")
    assert out.name == "A.ARW.xmp"
    assert (tmp_path / "A.xmp").exists() is False


def test_darktable_sidecar_is_patched_not_replaced(tmp_path):
    img = _image(tmp_path)
    sidecar = tmp_path / "A.ARW.xmp"
    sidecar.write_text(_HISTORY, encoding="utf-8")

    out = write_xmp(img, 5, "Green", naming="darktable", preserve_existing=False)

    assert out == sidecar
    text = sidecar.read_text(encoding="utf-8")
    assert 'xmp:Rating="5"' in text
    assert "exposure 1.20" in text, "darktable develop history was destroyed"
    assert "darktable:history" in text


def test_patch_writes_the_label_when_absent(tmp_path):
    img = _image(tmp_path)
    sidecar = tmp_path / "A.ARW.xmp"
    sidecar.write_text(_HISTORY, encoding="utf-8")

    write_xmp(img, 5, "Green", naming="darktable", preserve_existing=False)

    text = sidecar.read_text(encoding="utf-8")
    assert ('xmp:Label="Green"' in text) or ("<xmp:Label>Green</xmp:Label>" in text)


def test_patch_keeps_element_form_when_that_is_what_is_there(tmp_path):
    img = _image(tmp_path)
    sidecar = tmp_path / "A.ARW.xmp"
    sidecar.write_text(
        _HISTORY.replace('xmp:Rating="0"', "")
        .replace("</rdf:Description>",
                 "  <xmp:Rating>0</xmp:Rating>\n  </rdf:Description>"),
        encoding="utf-8")

    write_xmp(img, 3, "", naming="darktable", preserve_existing=False)

    text = sidecar.read_text(encoding="utf-8")
    assert "<xmp:Rating>3</xmp:Rating>" in text
    assert "exposure 1.20" in text
