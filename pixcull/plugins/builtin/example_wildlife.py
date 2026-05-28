"""Example built-in plugin — adds a "behavior" rubric axis + a
"wing_clipped" cull reason for wildlife / bird photographers.

This file ships with PixCull as documentation-by-code.  Users can
copy it to ``~/.pixcull/plugins/`` and customise; or write their
own following the same shape.

To enable:  ``pixcull plugins enable example_wildlife``
"""

MANIFEST = {
    "name":    "Wildlife axis + cull-reason pack",
    "version": "1.0.0",
    "author":  "PixCull project",
    "scope":   ["rubric_axis", "cull_reason"],
}


def register(api):
    """Called by the plugin runtime at app boot."""
    api.register_rubric_axis(
        id="behavior",
        label_en="Animal behavior",
        label_zh="动物动作",
        description="Capturing dynamic action vs static rest",
        weight=0.8,
    )
    api.register_cull_reason(
        id="wing_clipped",
        label_zh="翅膀被切",
        label_en="Wing clipped",
        applies_to=["wildlife", "birds"],
    )
    api.register_cull_reason(
        id="eye_contact_missed",
        label_zh="眼神错失",
        label_en="Missed eye contact",
        applies_to=["wildlife", "portrait"],
    )
