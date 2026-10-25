"""Plain-language help for the live Onshape steps.

Keep each guide aligned with the ordered steps in its lesson. The main action
remains the short instruction; this text explains it for a first-time user.
"""

ONSHAPE_GUIDES = {
    "parametric-thinking": (
        "Draw a simple box on paper. Add two groups of holes, then label what the bracket must do before opening a CAD tool.",
        "These are the few numbers you may need to change later. Write each name beside the part of the drawing it controls.",
        "A sketch is a flat drawing. An extrusion gives it thickness. A cut makes holes. A fillet or chamfer softens an edge.",
        "For example, 'symmetric' means the two hole centers stay the same distance from the middle, even after an edit.",
        "If the width grows from the center, each side moves outward. The holes can stay put because their spacing has its own control.",
    ),
    "workspace-navigation": (
        "A document is the project file; a Part Studio is the tab where you make the bracket. Give both names before drawing.",
        "Look at the tabs along the bottom. A Part Studio makes parts; an Assembly is where you position separate parts together.",
        "Find the workspace units before typing a measurement. Decide whether every length in this practice model uses millimeters or inches.",
        "Use the view cube to return to a straight-on view after turning the model. These camera moves do not change the part.",
        "Choose names such as Base sketch, Bracket thickness, Mounting holes, and Edge fillet. You can apply them as features are created.",
    ),
    "fully-defined-sketch": (
        "The origin is the point where the sketch axes cross. Select a flat plane such as Top, then use that point as the bracket's center.",
        "Choose Center point rectangle, click the origin for its center, then click a corner. Exact size comes from dimensions later.",
        "Make these lines construction geometry so they guide other shapes but do not become edges of the solid bracket.",
        "Place one circle center, then make the second center mirror it across the middle line. Give matching holes one shared diameter.",
        "Add only the measurements needed to stop movement. Drag an edge or circle center to check that nothing can still slide.",
    ),
    "part-features": (
        "Select only the closed outer rectangle for Extrude. Choose New so Onshape creates one bracket part.",
        "In the Extrude distance box, enter the planned thickness with its unit. You will connect this distance to a named variable later.",
        "Cut the circles through the entire part. Rotate the view and check the openings on the back face too.",
        "A pattern is a second group of holes for another mounting option. Give its center spacing its own dimension and avoid overlapping holes.",
        "A fillet rounds an edge; a chamfer cuts it at an angle. Select only the exposed edges you intend to make safer.",
    ),
    "configurable-design": (
        "A variable is a named number. Create each name with a length value; use # when you refer to that name in a dimension.",
        "Edit the rectangle's width dimension and enter #bracketWidth. The sketch should keep the same shape at first.",
        "Edit Extrude and put #bracketThickness in its distance field. Check that the bracket is still one part.",
        "Edit the dimension between the primary hole centers and enter #primaryHoleSpacing. Do not change each hole separately.",
        "Change one variable, check the result, then restore or record its value before changing the next one. Look for broken features or holes near an edge.",
    ),
    "inspect-communicate": (
        "Use Measure and write down the actual model values. For edge material, measure from a hole's outside edge to the nearest plate edge.",
        "Turn the part over and look along its sides. A top view alone can hide a hole that did not cut all the way through.",
        "Read the unit shown for a known dimension. Rename key items in the feature list so a teammate can find the sketch, cuts, and finish.",
        "Change the second hole group without moving the original group. Write down the variable or dimension you changed and what stayed fixed.",
        "Save one angled view showing thickness and both hole groups. Record the planned file type, unit, and filename in your notes.",
    ),
    "brief": (
        "Write down the available space and the design choices before modeling. 'Envelope' means the space the drivetrain must fit inside.",
        "Make a table with value, unit, source, and status. Mark a value provisional if you have not checked the actual part or drawing.",
        "Create one named number for each size you expect to revise. Enter units with lengths so a later edit stays meaningful.",
        "Draw a center-based rectangle from above. Its length and width show the maximum space available, not the final plate outline.",
        "Use dashed construction shapes to mark places the design must avoid. Label which limits are fixed and which can change.",
    ),
    "layout": (
        "A datum is a reference used to locate other things. Put one centerline front to back and another left to right through the origin.",
        "Mark each wheel's center with a point. Dimension one side, then use symmetry so the opposite wheel stays matched.",
        "A wheel sweep is the space a turning wheel occupies. Use circles for its diameter and note its width beside the top-view sketch.",
        "Draw simple shapes for the motor's outside size and mark its output shaft center. Use measured dimensions rather than a detailed motor model.",
        "Mark where each plate sits and leave room to reach bolts and remove parts. This access space matters even if it is empty in CAD.",
        "Change one value in the layout and see what moves. If one wheel or plate stays behind, repair its sketch relationships before building parts.",
    ),
    "plates": (
        "Draw the plate edge around the layout. Leave enough material around bearing and bolt holes for the selected manufacturing method.",
        "Extrude the first outline as a new part. Use the plate-thickness variable for its depth and name the part Left plate.",
        "Make the second plate from the same references so edits affect both. Locate its inner face using the plate-spacing control.",
        "Only remove material where you can explain the benefit. Keep a continuous route for loads between wheel supports and frame connections.",
        "Round or bevel only edges the chosen process can produce. Add these finishing features after the holes and main outline are stable.",
        "Edit spacing and thickness separately. Check that both plates still line up and the pair still fits within the available space.",
    ),
    "interfaces": (
        "A bearing seat is the hole or pocket that locates a bearing. Use the actual bearing's outside size and record the fit you intend.",
        "Simple cylinders are enough for early shaft and wheel models. Their center axes must line up with the bearing axes.",
        "Use the chosen motor's drawing to place its bolt holes and shaft center. Add a simple box for the motor body to check space.",
        "A bolt hole needs room for its head or nut and for a tool to turn it. Mark those spaces before committing the hole locations.",
        "Use shared sketch references for holes that must line up on both plates. Keep different left and right features separate and named.",
        "Measure the thinnest material beside each opening. Imagine the force from the wheel traveling through the bearing and plate to the frame.",
    ),
    "assembly": (
        "An Assembly tab holds copies of the finished parts. Fix one plate or frame part so the whole model does not drift when dragged.",
        "A Fastened mate locks two items together. Use it for hardware that should move as one piece with its support.",
        "A Revolute mate lets a part rotate around one axis. Drag the wheel or shaft to confirm it turns without sliding sideways.",
        "A section view shows a cut through the model. Interference detection highlights parts occupying the same space; inspect each result.",
        "Plan the repair sequence. List which bolts and parts come off first, and check that a tool can reach them.",
        "Widen the wheel model, then move internal parts as needed without growing the outer limit. Measure and record the smallest remaining gap.",
    ),
}


def add_onshape_guides(course):
    """Attach one guide to every live Onshape step and fail on content drift."""
    if course["platform"] != "onshape":
        return course
    for lesson in course["lessons"]:
        guides = ONSHAPE_GUIDES[lesson["id"]]
        if len(guides) != len(lesson["steps"]):
            raise ValueError(f"Beginner guide count differs for {lesson['id']}")
        for step, guide in zip(lesson["steps"], guides):
            step["beginner_guide"] = guide
    return course
