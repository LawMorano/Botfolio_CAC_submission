"""Quick Start and CAD Mental Model course content."""

COURSE_SLUG = "quick-start-cad-mental-model"

CHALLENGE = (
    "Adapt the bracket for a second mounting-hole pattern while preserving the original "
    "design intent. Record which controlling dimensions changed, which relationships did "
    "not change, and why."
)

ARTIFACTS = (
    "A clear final view of the rectangular mounting bracket.",
    "Evidence of the original and second mounting-hole patterns.",
    "A short parameter or variable table naming width, thickness, and hole spacing.",
    "A brief revision note explaining which controlling values changed and why.",
    "The intended export format, units, and filename, documented even if no file is uploaded.",
)

RUBRIC = (
    {"criterion": "Parametric structure", "evidence": "Named dimensions or parameters control the bracket and update downstream geometry."},
    {"criterion": "Sketch stability", "evidence": "The base sketch is fully constrained with intentional relationships and a clear origin strategy."},
    {"criterion": "Manufacturable form", "evidence": "Thickness, holes, and edge treatments produce a plausible mounting part with adequate surrounding material."},
    {"criterion": "Verification and communication", "evidence": "The learner checks units and critical dimensions and records a readable final view and revision explanation."},
)


def _step(title, action, reason, result, note=""):
    return {"title": title, "action": action, "reason": reason, "result": result, "note": note}


def _lesson(identifier, title, summary, minutes, outcome, relevance, concepts, setup,
            steps, checkpoints, mistakes, practice, checklist, vocabulary=(),
            specifications=(), media=(), self_check=()):
    return {
        "id": identifier, "title": title, "summary": summary,
        "estimated_minutes": minutes, "outcome": outcome, "ftc_relevance": relevance,
        "concepts": concepts, "required_setup": setup, "steps": steps,
        "checkpoints": checkpoints, "common_mistakes": mistakes,
        "practice": practice, "completion_checklist": checklist,
        "vocabulary": vocabulary, "reference_specifications": specifications,
        "media": media,
        "self_check": self_check or ({"question": "What result shows this lesson's outcome is complete?", "answer": outcome},),
    }


def lessons_for(platform):
    onshape = platform == "onshape"
    product = "Onshape" if onshape else "Fusion 360"
    workspace = "document" if onshape else "design"
    parameter = "variable" if onshape else "user parameter"
    parameter_plural = "variables" if onshape else "user parameters"

    return (
        _lesson(
            "parametric-thinking", "How parametric CAD thinks",
            "Read a model as a chain of relationships instead of a pile of copied geometry.", 12,
            "Identify the sketches, constraints, dimensions, and features that should control a simple FTC bracket.",
            "FTC parts change as hardware and packaging decisions evolve; design intent lets a model absorb those changes without a redraw.",
            ("Sketches", "Dimensions", "Constraints", "Features", "Parts and assemblies", "Design intent"),
            (f"Open {product} and be ready to inspect a simple bracket concept; no starter file is required.",
             "Have paper or a notes app available for a short dependency map."),
            (
                _step("Separate intent from shape", "Describe the bracket as a rectangular body with thickness and two mounting-hole patterns.", "Naming intent before commands prevents accidental dimensions from becoming requirements.", "Your description states what must remain true without naming a CAD command."),
                _step("Choose controlling values", "List body width, body height, thickness, primary hole spacing, hole diameter, and edge radius as candidate controls.", "A small set of controls makes later revisions predictable.", "Every major feature traces to a named value rather than an eyeballed position."),
                _step("Map the feature chain", "Order the conceptual model as base sketch, solid feature, holes, then edge treatment.", "Later features depend on earlier geometry, so feature order communicates engineering intent.", "You can point from each finished detail back to the sketch or feature that creates it."),
                _step("Define relationships", "Mark centered, symmetric, horizontal, vertical, and equal relationships that should survive a size change.", "Relationships encode intent; copied geometry only preserves a one-time appearance.", "Moving one controlling location would move its related geometry consistently."),
                _step("Predict an edit", "Imagine increasing bracket width while holding hole spacing constant, then explain which edges and holes should move.", "Predicting propagation is the simplest test of a parametric plan.", "Your prediction distinguishes fixed hole spacing from body-edge growth."),
            ),
            ("The dependency map contains at least one sketch, one solid feature, and one finishing feature.",
             "The learner can explain why a relationship is more durable than copying a second hole."),
            ("Mistake: treating every visible measurement as independent. Recovery: circle only the few values that represent requirements.",
             "Mistake: confusing a part with its assembly placement. Recovery: describe the part's shape first, then where it will be used."),
            "Change the imagined fastener diameter. Identify which feature changes and which bracket dimensions should remain unaffected.",
            ("I can distinguish sketches, features, parts or components, and assemblies.",
             "I identified controlling dimensions and persistent relationships.",
             "I predicted the effect of editing an early value."),
            ("parametric", "constraint", "feature", "design intent", "dependency"),
            media=("Needed asset: annotated dependency diagram for a simple bracket; not yet available.",),
        ),
        _lesson(
            "workspace-navigation", "Navigate and organize the workspace",
            f"Create a clearly named {product} workspace and locate the controls needed for the bracket.", 13,
            f"Prepare an organized {product} workspace with correct units and names for the bracket project.",
            "Clear structure helps teammates find editable geometry, review revisions, and avoid manufacturing the wrong version.",
            (("Documents", "Tabs", "Part Studios", "Assemblies", "View controls", "Units", "Naming conventions") if onshape else
             ("Projects", "Designs", "Browser", "Timeline", "Components", "View controls", "Units", "Naming conventions")),
            (f"Sign in to {product} or open an available classroom installation.",
             "Know whether the team normally designs in millimeters or inches."),
            ((
                _step("Create the document", "Create a document named FTC Mounting Bracket — Practice and rename its first Part Studio Bracket.", "Document and tab names make shared browser-based work searchable.", "The document title and Part Studio tab both describe their purpose."),
                _step("Survey the tabs", "Locate the tab bar and identify where a Part Studio and an Assembly would live; keep the bracket in the Part Studio.", "Tabs separate modeling contexts while keeping related work together.", "You can explain which tab creates the part and which would position it later."),
                _step("Set units", "Open workspace units and confirm the team's chosen length unit.", "A correct number in the wrong unit still creates unusable hardware.", "A known reference measurement displays in the intended unit."),
                _step("Practice view control", "Fit the view, orbit, pan, zoom, and return to a standard front or top view.", "Reliable view control reduces selection errors during sketching.", "You can return to a square-on sketching view without changing geometry."),
                _step("Apply naming conventions", "Plan names for the base sketch, solid feature, mounting holes, and edge finish.", "Feature names turn the history into an explanation another student can audit.", "The planned names describe function rather than default sequence numbers."),
            ) if onshape else (
                _step("Create the design", "Create a design in the team's project and name it FTC Mounting Bracket — Practice.", "Project and design names make shared work searchable and reduce version confusion.", "The design is saved in the intended project with a descriptive name."),
                _step("Create the component", "Create and activate a component named Bracket before sketching.", "An intentional component keeps geometry, origin, and history organized for later assembly use.", "The Browser shows an active Bracket component rather than only a loose body."),
                _step("Read the Browser and timeline", "Locate the component in the Browser and the feature timeline at the bottom of the design.", "These two views show model ownership and feature order.", "You can identify where the bracket geometry belongs and where future operations will appear."),
                _step("Set units and views", "Confirm document units, then practice fit, orbit, pan, zoom, and a standard front or top view.", "Units protect physical scale; controlled views reduce selection errors.", "The unit is intentional and you can return to a square-on sketch view."),
                _step("Apply naming conventions", "Plan names for the base sketch, extrusion, mounting holes, and edge finish.", "Names make the timeline readable during review and repair.", "The planned names describe function rather than default operation numbers."),
            )),
            (f"The {workspace} and modeling context use descriptive names.", "Units are confirmed before any dimensions are entered.", "The learner can return to an orthographic view after orbiting."),
            ("Mistake: starting geometry in an ambiguously named workspace. Recovery: rename it before continuing.",
             "Mistake: changing displayed units after entering unexplained numbers. Recovery: confirm units first, then inspect every existing dimension."),
            "Add a naming prefix your team could use for practice files, then explain how production designs would differ.",
            ("My workspace and modeling context are named.", "I confirmed units.", "I located the model organization and feature history.", "I can control and reset the camera view."),
            media=(f"Needed asset: labeled {product} workspace screenshot; not yet available.",),
        ),
        _lesson(
            "fully-defined-sketch", "Create a fully defined base sketch",
            "Build a centered base profile and primary hole pattern whose remaining freedom is intentional and visible.", 18,
            "Create a fully constrained bracket sketch driven by named dimensions and geometric relationships.",
            "Stable sketches keep mounting patterns aligned when robot packaging dimensions change.",
            ("Origin strategy", "Centered geometry", "Horizontal and vertical", "Symmetry", "Construction geometry", "Fully constrained sketches"),
            (f"Open the Bracket modeling context created in the previous lesson.", "Choose provisional dimensions that are visibly labeled for later hardware verification."),
            (
                _step("Start at the origin", "Create a sketch on a principal plane and place the bracket center at the origin.", "A centered origin gives symmetry a stable reference and simplifies later assembly placement.", "The origin lies at the intended center of the base profile."),
                _step("Draw the base profile", "Create a center rectangle or a symmetric rectangular profile for the mounting body.", "Centered geometry can grow equally in both directions when width or height changes.", "Opposite edges remain centered about the origin."),
                _step("Add construction axes", "Add horizontal and vertical construction centerlines through the origin.", "Construction geometry provides references without becoming part of the solid profile.", "The centerlines are visibly construction geometry and do not close extra regions."),
                _step("Relate the primary holes", "Create the first hole center, mirror or constrain the partner about a centerline, and make equivalent holes equal where appropriate.", "Relationships preserve a pattern more reliably than two unrelated positions.", "Both centers move symmetrically when spacing changes."),
                _step("Dimension the intent", "Add dimensions for body width, body height, hole spacing, edge offset as needed, and hole diameter.", "Dimensions should express requirements without duplicating constraints.", "The solver reports a fully constrained sketch and no geometry moves when dragged."),
            ),
            ("The profile is centered on the origin.", "Hole centers are defined by relationships and dimensions, not separate visual placement.", "The sketch reports fully constrained without redundant-constraint warnings."),
            ("Mistake: dimensioning both symmetric sides independently. Recovery: keep one controlling dimension and add symmetry.",
             "Mistake: using solid lines for center references. Recovery: convert reference axes to construction geometry.",
             "Mistake: fixing geometry to hide missing constraints. Recovery: remove the fix and constrain its real relationship to the origin."),
            "Change the body width while holding primary hole spacing constant. Confirm symmetry and explain which edge offsets changed.",
            ("The profile uses a deliberate origin.", "Construction geometry does not create solid regions.", "The primary holes remain symmetric.", "The sketch is fully constrained."),
            specifications=("Selected fastener clearance-hole diameter", "Required primary hole spacing", "Minimum desired material around each hole"),
            media=("Needed asset: under-constrained versus fully constrained sketch comparison; not yet available.",),
        ),
        _lesson(
            "part-features", "Turn the sketch into a part",
            "Build thickness, holes, and safe edge treatments in an intentional feature order.", 17,
            "Produce a single organized bracket part with editable thickness, mounting holes, and filleted or chamfered edges.",
            "Feature order affects whether an FTC part stays editable when dimensions or mounting patterns change.",
            ("Extrusion", "Thickness", "Hole features", "Fillets and chamfers", "Feature order"),
            (("Open the Bracket Part Studio and confirm the base sketch is fully constrained.",) if onshape else
             ("Activate the Bracket component and confirm the base sketch is fully constrained.",)),
            (
                _step("Create the structural solid", ("Extrude the base profile as a new part in the Part Studio." if onshape else "Extrude the base profile as a new body inside the active Bracket component."), "The first solid feature establishes the structural mass before details are removed.", "One rectangular bracket solid appears in the intended modeling context."),
                _step("Set editable thickness", "Enter a clearly named thickness value rather than accepting an unexplained default.", "Thickness affects stiffness, fastener engagement, and packaging.", "Editing the thickness value changes only the depth of the bracket."),
                _step("Create the primary holes", "Use the sketched circles or a hole-cutting feature to remove the primary mounting holes through the part.", "A through condition avoids leaving accidental membranes when thickness changes.", "The primary holes pass fully through the solid."),
                _step("Add the second pattern", "Create at least one additional mounting-hole pattern with a distinct spacing requirement.", "Multiple interfaces make the part configurable for real FTC packaging choices.", "Two recognizable mounting patterns exist without overlapping unintentionally."),
                _step("Finish exposed edges", "Apply a modest fillet or chamfer after the structural solid and holes are valid.", "Edge treatments reduce sharp edges but are fragile when placed before defining geometry.", "Selected exposed edges have a consistent treatment and the feature history remains logical."),
            ),
            ("The bracket is one organized part or component, not disconnected solids.", "Thickness is editable and all intended holes pass through.", "Edge treatments occur after structural features in the history."),
            ("Mistake: adding finishing features before holes. Recovery: reorder or recreate the edge treatment after structural cuts.",
             "Mistake: creating a loose body in Fusion. Recovery: move or recreate it inside the active Bracket component.",
             "Mistake: using a blind cut tied to old thickness. Recovery: use an appropriate through-all extent and inspect both faces."),
            "Suppress the edge treatment, change the body height, then restore it. Note whether the selected edges remain valid.",
            ("The bracket has one rectangular body.", "Thickness is deliberately controlled.", "Both hole patterns cut through the part.", "A fillet or chamfer follows structural features."),
        ),
        _lesson(
            "configurable-design", "Make the design configurable",
            f"Replace important literal values with {parameter_plural} and test downstream updates.", 17,
            f"Drive bracket width, thickness, and hole spacing with named {product} {parameter_plural}.",
            "Configurable models let FTC teams compare packaging options without forking fragile copies.",
            (("Variables", "Expressions", "Referenced dimensions", "Downstream updates") if onshape else
             ("User parameters", "Expressions", "Referenced dimensions", "Downstream updates")),
            ("Open the completed bracket and note its current width, thickness, and primary hole spacing.",),
            (
                _step(f"Create named {parameter_plural}", ("Create #bracketWidth, #bracketThickness, and #primaryHoleSpacing variables." if onshape else "Open Change Parameters and create bracketWidth, bracketThickness, and primaryHoleSpacing user parameters."), "Names expose the model's intended controls and their units.", f"Three named {parameter_plural} appear with length units."),
                _step("Reference bracket width", f"Edit the sketch width dimension so its expression references the bracket-width {parameter}.", "The named control becomes the source of truth instead of a duplicated number.", "Changing bracket width updates the centered outer edges."),
                _step("Reference thickness", f"Edit the extrusion distance to reference the thickness {parameter}.", "The structural depth should respond from the same documented control set.", "Changing thickness updates the solid without leaving partial holes."),
                _step("Reference hole spacing", f"Edit the primary pattern spacing to reference the hole-spacing {parameter}.", "A named interface dimension is easier to verify against hardware.", "Both primary hole centers move symmetrically when spacing changes."),
                _step("Run a configuration test", "Change width, thickness, and hole spacing one at a time, regenerate, and inspect the full model after each edit.", "Testing one input at a time isolates broken relationships and reveals hidden dependencies.", "All three edits rebuild without errors, asymmetry, or lost edge treatments."),
            ),
            (f"The three named {parameter_plural} drive real dimensions.", "The sketch stays fully constrained after each edit.", "Holes remain through the part and retain adequate visible material."),
            ("Mistake: creating a named value but leaving the old literal dimension in place. Recovery: edit the dimension and reference the name explicitly.",
             "Mistake: changing all controls at once. Recovery: restore the last valid state and test one input at a time.",
             "Mistake: omitting units from an expression. Recovery: confirm each named value has the intended length unit."),
            "Create a safe narrow and wide bracket configuration. Record the first limit that makes a hole too close to an edge.",
            (f"Width, thickness, and hole spacing use named {parameter_plural}.", "Each control was tested independently.", "The model rebuilds and remains symmetric.", "I recorded a practical configuration limit."),
            media=(f"Needed asset: {product} parameter editor example; not yet available.",),
        ),
        _lesson(
            "inspect-communicate", "Inspect, revise, and communicate",
            "Audit the bracket, complete the independent revision, and prepare a clear engineering record.", 13,
            "Verify critical geometry and document a configurable bracket that another FTC teammate can understand.",
            "A CAD model is useful only when a teammate can trust its units, clearances, revision intent, and fabrication output.",
            ("Measure tools", "Visual inspection", "Minimum material", "Feature naming", "Export awareness", "Design communication"),
            ("Open the final bracket configuration.", "Have the selected fastener specification or a clearly labeled provisional value available."),
            (
                _step("Measure critical geometry", "Measure overall width, thickness, hole diameter, hole spacing, and the narrowest material between a hole and an edge.", "Independent measurement verifies that expressions produced the intended physical result.", "Measured values agree with the controlling values and no hole breaks through an outer edge."),
                _step("Inspect every orientation", "Use standard and angled views to check both faces, all holes, and every treated edge.", "A single attractive view can conceal incomplete cuts or unintended geometry.", "Both faces show complete holes and the edge treatment appears only where intended."),
                _step("Confirm units and names", "Confirm workspace units and rename important sketches and features by function.", "Clear units and history labels make reviews and future edits safer.", "The model tree or history reads as an understandable build sequence."),
                _step("Complete the challenge", "Add or revise a second mounting-hole pattern while preserving the original relationships; record the controls you changed.", "Transfer to a new interface demonstrates design intent rather than command memorization.", "Both patterns coexist, the model rebuilds, and the revision note names the changed controls."),
                _step("Prepare the record", "Capture a clear isometric view and document the intended export format, units, and filename without uploading a file.", "Fabrication handoff requires deliberate format and scale choices.", "The view is readable and the export note specifies a format such as STEP for exchange or STL for an appropriate mesh workflow."),
            ),
            ("Measured critical values match their named controls.", "Minimum material around every hole is visibly checked against the team's requirement.", "The final view and revision note explain the result without relying on hidden model state."),
            ("Mistake: trusting dimension labels without measuring the result. Recovery: use the measure tool on finished geometry.",
             "Mistake: treating an export format as universally correct. Recovery: choose it based on the downstream manufacturing or exchange workflow.",
             "Mistake: capturing an ambiguous perspective. Recovery: fit the model, use an isometric view, and keep holes visible."),
            CHALLENGE,
            ("I measured the finished geometry.", "I checked units and minimum material around holes.", "Important features are named.", "I completed and explained the second-pattern revision.", "I documented a clear view and intended export details."),
            specifications=("Selected fastener diameter", "Team minimum edge distance or material rule", "Intended fabrication or exchange format"),
            media=("Needed asset: final bracket checkpoint image; not yet available.",),
        ),
    )


def build_course(platform, pathway_name):
    lessons = lessons_for(platform)
    return {
        "slug": COURSE_SLUG, "platform": platform,
        "title": "Quick Start and CAD Mental Model",
        "summary": "Build a configurable FTC mounting bracket while learning how parametric CAD preserves design intent.",
        "level": "Start Here", "difficulty": "Beginner",
        "duration_minutes": sum(lesson["estimated_minutes"] for lesson in lessons),
        "status": "Live",
        "outcome": "A configurable FTC mounting bracket with a rectangular body, two hole patterns, named controls, editable thickness, treated edges, and a documented final result.",
        "prerequisites": ("No prior CAD experience",),
        "skills": ("Parametric thinking", "Fully constrained sketches", "Feature order", "Configuration", "Design verification"),
        "tools": (pathway_name, "Selected or provisional fastener dimensions", "Notes for the final revision explanation"),
        "lessons": lessons,
        "brief": "Create a small, editable mounting bracket that demonstrates the mental model used throughout the CAD Academy.",
        "objectives": ("Organize a CAD workspace and describe its modeling contexts.", "Encode design intent with constraints, dimensions, and named controls.", "Build and verify a configurable part.", "Communicate a revision and fabrication-aware result."),
        "constraints": ("Use a rectangular mounting body and at least two mounting-hole patterns.", "Keep dimensions provisional until checked against selected hardware.", "Preserve symmetry and minimum material around holes during configuration changes."),
        "checkpoints": tuple(checkpoint for lesson in lessons for checkpoint in lesson["checkpoints"][:1]),
        "challenge": CHALLENGE, "artifacts": ARTIFACTS, "rubric": RUBRIC,
        "related": ("parallel-plate-drivetrain",),
        "equivalent_slug": COURSE_SLUG,
    }
