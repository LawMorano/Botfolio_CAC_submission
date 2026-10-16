"""The 3D viewer cannot be steered into a view it will not come back from.

The wheel gives OrbitControls a fixed multiplier per notch and nothing else,
so with no limits set the orbit radius runs away in both directions: about
twenty-five notches in and the camera is inside the mesh, where back-face
culling leaves nothing but the background colour, and about sixty-five out and
the model is past the far plane. Either way the picture goes flat and dragging
stops changing anything visible, which is what "locks up at some view" looks
like from the outside. The end of the zoom-in is genuinely unrecoverable: the
radius is only ever multiplied, so once it reaches zero no gesture can grow it
again, and a camera captured at that point is stored and replayed on every
later visit.

The behaviour is all JavaScript, so it is exercised by
tests/viewer_orbit_harness.mjs, which drives the real viewer against the real
three.js with only the WebGL calls stubbed. What is checked here is that the
limits are actually written down in the source, and that the pages still hand
the viewer a way back to the default view.
"""

import os
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "static" / "viewer.js"
HARNESS = Path(__file__).parent / "viewer_orbit_harness.mjs"


class OrbitLimitTests(unittest.TestCase):
    """The limits the viewer promises, read off the source."""

    def setUp(self):
        self.source = VIEWER.read_text(encoding="utf-8")

    def test_the_zoom_limits_bracket_the_normalised_model(self):
        # _normalize() scales every model to a bounding sphere of radius 1, and
        # that sphere comes from the box diagonal, so a corner of the mesh sits
        # at exactly 1 and the near limit has to clear it.
        self.assertIn("const MIN_ORBIT = 1.4;", self.source)
        self.assertIn("const MAX_ORBIT = 20;", self.source)

    def test_the_limits_are_handed_to_the_controls(self):
        for line in ("this.controls.minDistance = MIN_ORBIT;",
                     "this.controls.maxDistance = MAX_ORBIT;",
                     "this.controls.maxTargetRadius = MAX_PAN;"):
            with self.subTest(line=line):
                self.assertIn(line, self.source)

    def test_the_limits_stay_inside_the_frustum(self):
        # The model spans radius - 1 to radius + 1 in camera distance, so each
        # limit has to clear its plane by more than the model itself.
        self.assertIn("new THREE.PerspectiveCamera(45, (w || 1) / (h || 1), 0.01, 100)",
                      self.source)

    def test_a_hidden_viewer_stops_rendering(self):
        # The viewer lives in a <dialog> that nothing tears down on close, and
        # destroy() has no callers, so this is the only thing stopping it.
        self.assertIn("if (!this.container.clientWidth || !this.container.clientHeight) return;",
                      self.source)

    def test_the_pixel_ratio_is_capped(self):
        self.assertIn("Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO)",
                      self.source)


class ResetAffordanceTests(unittest.TestCase):
    """Every page that shows the viewer keeps a way back to the default view."""

    def test_each_viewer_page_offers_a_reset(self):
        for name in ("design_detail.html", "edit_design.html", "submit.html"):
            with self.subTest(page=name):
                page = (ROOT / "templates" / name).read_text(encoding="utf-8")
                self.assertIn("Reset view", page)


class OrientationSequenceTests(unittest.TestCase):
    """The two structural traps the orientation sequence has to stay clear of.

    Its arithmetic is exercised for real by the harness; these are the two
    things a passing harness would not notice, because neither is arithmetic.
    """

    def test_the_sequence_never_opens_a_second_dialog(self):
        # The design page's viewer already sits in an open <dialog>, and
        # showModal() puts only the topmost one in the top layer -- everything
        # under it goes inert. A dialog for the warning screen would therefore
        # freeze the model during the two steps that ask the user to turn it.
        source = (ROOT / "static" / "viewer-orientation.js").read_text(encoding="utf-8")
        # Matched on the call rather than the bare word: the file explains this
        # trap in its own header comment, which mentions showModal by name.
        self.assertNotIn(".showModal(", source)
        self.assertNotIn("createElement('dialog')", source)
        # What it does instead -- an ordinary child of the viewer's container,
        # which is inside whatever dialog is open rather than competing with it.
        self.assertIn("host.append(overlay);", source)

    def test_the_two_captures_have_to_be_far_enough_apart_to_mean_something(self):
        # Only the part of the top at right angles to the front is used, so two
        # views a few degrees apart leave that remainder to whichever pixel the
        # drag finished on.
        self.assertIn("const MIN_AXIS_SEPARATION = 0.1;",
                      VIEWER.read_text(encoding="utf-8"))


NODE_BINARY = os.environ.get("BOTFOLIO_NODE_BINARY") or shutil.which("node")


@unittest.skipUnless(NODE_BINARY, "node is not installed")
class OrbitBehaviourTests(unittest.TestCase):
    """Run the JavaScript harness and surface its failures here."""

    def test_the_viewer_cannot_be_steered_into_a_dead_view(self):
        result = subprocess.run(
            [NODE_BINARY, str(HARNESS)],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0,
                         f"\n{result.stdout}\n{result.stderr}")
        self.assertIn("passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
