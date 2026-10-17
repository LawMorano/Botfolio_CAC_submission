"""Sketching and Parameters/Variables foundation course content."""

COURSE_SLUG = "sketching-and-parameters"

CHALLENGE = (
    "Adapt the motor-mounting plate to a second verified motor or mounting pattern while "
    "preserving the plate center, symmetry, minimum edge material, editable thickness, "
    "named parameters, and correct hole relationships. Explain which dimensions came from "
    "hardware documentation or measurement, which values are design choices, which parameters "
    "changed, what remained fixed, and how the sketch proves its design intent."
)

ARTIFACTS = (
    "A fully constrained plate sketch showing its origin, construction centerlines, and mounting-hole relationships.",
    "A finished plate with editable thickness and minimum edge material checked against the team's requirement.",
    "A parameter table separating verified hardware dimensions from design choices.",
    "Before-and-after evidence for the second verified motor or mounting pattern.",
    "A short design-intent explanation naming changed parameters and preserved relationships.",
)

RUBRIC = (
    {"criterion": "Verified inputs", "evidence": "Hardware-derived values cite documentation or measurement; design choices are labeled separately."},
    {"criterion": "Sketch intent", "evidence": "Origin, constraints, symmetry, and patterns keep the mounting layout fully constrained and centered."},
    {"criterion": "Configuration", "evidence": "Named parameters and expressions drive thickness, plate size, hole size, spacing, and edge material predictably."},
    {"criterion": "Diagnosis and communication", "evidence": "The learner repairs a broken relationship and explains the second-pattern adaptation with observable evidence."},
)

REFERENCE_SPECIFICATIONS = (
    "Motor mounting-hole diameter", "Horizontal and vertical mounting-hole spacing",
    "Motor shaft or pilot clearance envelope", "Motor body clearance envelope",
    "Selected fastener diameter", "Chosen plate thickness",
    "Team minimum edge-material requirement", "Source and verification status for each value",
)


def _step(title, action, reason, result, note=""):
    return {"title": title, "action": action, "reason": reason, "result": result, "note": note}


def _check(question, answer):
    return {"question": question, "answer": answer}


def _media(path, alt, caption):
    return {"path": path, "alt": alt, "caption": caption}


def _lesson(identifier, title, summary, minutes, outcome, relevance, concepts, setup,
            steps, checkpoints, mistakes, practice, checklist, vocabulary, self_check,
            media=()):
    return {
        "id": identifier, "title": title, "summary": summary,
        "estimated_minutes": minutes, "outcome": outcome, "ftc_relevance": relevance,
        "concepts": concepts, "required_setup": setup, "steps": steps,
        "checkpoints": checkpoints, "common_mistakes": mistakes,
        "practice": practice, "completion_checklist": checklist,
        "vocabulary": vocabulary, "reference_specifications": REFERENCE_SPECIFICATIONS,
        "self_check": self_check, "media": media,
    }


def lessons_for(platform):
    onshape = platform == "onshape"
    product = "Onshape" if onshape else "Fusion 360"
    context = "Part Studio" if onshape else "Motor Mount component"
    contexts = "Part Studios" if onshape else "Components"
    parameter = "variable" if onshape else "user parameter"
    parameters = "variables" if onshape else "user parameters"
    parameter_title = "Variables" if onshape else "User parameters"
    linear_pattern = "linear sketch pattern" if onshape else "rectangular pattern"
    linear_patterns = "Linear and circular sketch patterns" if onshape else "Rectangular and circular patterns"

    return (
        _lesson(
            "intent-planes-origin", "Design intent, sketch planes, and the origin",
            "Plan a motor-mounting plate around stable datums and verified hardware inputs.", 15,
            "Create an origin-centered plate skeleton on an intentional sketch plane and distinguish hardware requirements from design choices.",
            "Motor plates must stay aligned to shafts, gearboxes, and frames even when packaging dimensions change.",
            (contexts, "Design intent", "Sketch planes", "Origin", "Verified and provisional dimensions"),
            (f"Open a new {product} design and create or select a {context}.", "Collect documentation or measurements for one selected motor; mark unknown values provisional."),
            (
                _step("Classify the dimensions", "Create a two-column list: verified hardware dimensions and team design choices.", "A mounting pattern should follow real hardware while plate size and margin remain deliberate engineering choices.", "Every planned value has a source or is labeled as a choice or provisional value."),
                _step("Choose the sketch plane", "Select a principal plane that represents the broad face of the mounting plate.", "A principal plane creates a stable reference and makes the thickness direction obvious.", "The view is normal to the plane and the plate will thicken perpendicular to it."),
                _step("Anchor the plate center", "Start the base sketch with its intended plate center coincident with the origin.", "Centering simplifies symmetry, mirroring, and later placement in a robot assembly.", "The plate center cannot translate away from the origin."),
                _step("Represent the motor axis", "Add a point or construction intersection at the origin for the motor shaft or pilot axis.", "The motor axis is a functional datum that should not drift when the plate perimeter changes.", "The motor-axis reference remains at the plate center."),
                _step("Test the datum strategy", "Drag unconstrained outer geometry while watching the origin and motor-axis reference.", "A drag test reveals which freedoms are intentional before dimensions hide them.", "Outer geometry may move, but the functional center stays fixed."),
            ),
            ("The sketch is on a named principal plane.", "Plate center and motor axis coincide with the origin.", "Hardware dimensions and design choices are recorded separately."),
            ("Mistake: choosing a convenient face that may disappear. Recovery: recreate or redefine the sketch on a stable principal plane.", "Mistake: placing the motor axis by eye. Recovery: constrain it to the origin before adding the perimeter.", "Mistake: treating an online example as verified. Recovery: cite the selected motor documentation or measure the actual part."),
            "Choose a different plausible plate orientation and explain why the original sketch plane gives a more stable or readable model.",
            ("I separated hardware requirements from design choices.", "The plate center uses the origin.", "The motor axis has a stable datum.", "I can explain the selected sketch plane.", "Unknown values are marked provisional."),
            ("design intent", "datum", "sketch plane", "origin", "degree of freedom"),
            (_check("Why anchor the functional center before sizing the plate?", "It preserves the motor and plate center while outer dimensions change."), _check("Is plate width normally a hardware dimension or a design choice?", "Usually a design choice, unless another verified interface explicitly controls it.")),
            (_media("images/academy/degrees-of-freedom.svg", "A rectangle with arrows showing horizontal, vertical, and rotational degrees of freedom around a fixed origin.", "Unconstrained geometry can translate and rotate until relationships remove those freedoms."),),
        ),
        _lesson(
            "construction-references", "Construction geometry and reference lines",
            "Build a reference skeleton that guides the plate without creating unwanted solid regions.", 14,
            "Create construction centerlines and clearance envelopes that express the mounting plate's functional references.",
            "Centerlines keep motor holes symmetric; clearance envelopes expose collisions before material is cut.",
            ("Construction geometry", "Horizontal and vertical centerlines", "Clearance envelopes", "Reference skeletons"),
            ("Open the origin-centered sketch from lesson 1.", "Have the verified motor body and shaft or pilot clearance dimensions available."),
            (
                _step("Add horizontal and vertical centerlines", "Draw construction lines through the origin along both principal directions.", "These axes provide stable references for symmetry and hole spacing without forming plate edges.", "Two perpendicular construction lines intersect at the origin."),
                _step("Create the motor clearance envelope", "Draw a construction circle or rectangle representing the verified motor body or pilot clearance.", "An envelope communicates occupied space without becoming part of the cut profile.", "The clearance shape is centered and visibly marked as construction geometry."),
                _step("Add mounting-pitch references", "Place construction lines or a construction rectangle through the intended mounting-hole centers.", "Pitch references separate the mounting relationship from the appearance of individual circles.", "Future hole centers can be constrained to shared reference geometry."),
                _step("Sketch the material boundary", "Create a normal-geometry plate perimeter around the reference skeleton.", "Only the actual boundary should create the region used for the solid plate.", "The plate perimeter forms one closed region while references remain non-profile geometry."),
                _step("Audit line purpose", "Inspect every sketch entity and convert any guide accidentally left as normal geometry to construction geometry.", "Mixed line purpose causes extra regions, failed extrusions, and ambiguous intent.", "Only the desired perimeter and future holes participate in the profile."),
            ),
            ("Centerlines cross at the origin.", "Clearance and pitch references are construction geometry.", "The plate perimeter is a single closed normal-geometry region."),
            ("Mistake: extruding a clearance envelope as material. Recovery: convert it to construction geometry.", "Mistake: drawing short centerlines that do not communicate the full symmetry axis. Recovery: extend or dimension them through the working area.", "Mistake: projecting many unnecessary edges. Recovery: keep only stable functional references."),
            "Add a construction envelope for a cable connector or gearbox feature and verify it does not create another closed profile.",
            ("Both centerlines are construction geometry.", "Hardware clearance is represented.", "Mounting pitch has shared references.", "The plate boundary remains a valid closed profile.", "Every line has an explainable purpose."),
            ("construction geometry", "centerline", "reference line", "clearance envelope", "profile"),
            (_check("Should a motor-body clearance envelope create plate material?", "No. It should normally be construction geometry used for inspection and placement."), _check("What distinguishes a reference from a boundary?", "A reference guides relationships; a boundary participates in the profile that becomes material or a cut.")),
            (_media("images/academy/construction-symmetry.svg", "A centered plate outline with dashed horizontal and vertical construction centerlines and mirrored mounting holes.", "Construction centerlines expose symmetry without becoming part of the plate profile."),),
        ),
        _lesson(
            "geometric-constraints", "Geometric constraints",
            "Replace accidental placement with explicit relationships that survive edits.", 16,
            "Apply sketch constraints so the plate perimeter and mounting features preserve their intended orientation, equality, concentricity, and symmetry.",
            "A motor pattern that only looks aligned can shift during an FTC packaging revision and produce unusable holes.",
            ("Sketch constraints", "Horizontal and vertical", "Coincident", "Equal", "Concentric", "Symmetric"),
            ("Open the reference skeleton from lesson 2.", f"Locate the sketch constraint tools in {product}."),
            (
                _step("Constrain orientation", "Apply horizontal and vertical constraints to the perimeter edges and centerlines.", "Orientation constraints prevent a nearly rectangular plate from skewing during edits.", "Edges stay orthogonal while their size may still change."),
                _step("Close the perimeter", "Use coincident constraints at every intended corner rather than relying on visual overlap.", "Tiny gaps can prevent feature creation even when endpoints appear connected.", "Dragging a corner keeps adjacent endpoints joined and the profile remains closed."),
                _step("Relate equivalent holes", "Make mounting-hole circles equal when the verified hardware uses one hole diameter.", "One diameter relationship prevents inconsistent edits across equivalent holes.", "Changing the controlling diameter updates every related circle."),
                _step("Align functional centers", "Constrain the motor-clearance center concentric with the origin and hole centers coincident with pitch references.", "Concentric and coincident relationships encode the actual hardware interface.", "The motor clearance stays centered and holes remain on their intended reference lines."),
                _step("Apply symmetry", "Constrain paired hole centers symmetrically about the relevant construction centerline.", "Symmetry preserves the plate center and reduces duplicated location dimensions.", "Dragging a permitted point moves its partner equally in the opposite direction."),
                _step("Inspect remaining freedom", "Drag each entity gently and identify any motion still permitted by the solver.", "Constraints should remove only unwanted freedom; dimensions will control intended size and spacing next.", "Remaining motion corresponds to missing size or spacing values, not broken relationships."),
            ),
            ("The perimeter stays rectangular and closed during drag tests.", "Equivalent holes remain equal.", "Paired holes remain symmetric about construction axes.", "No entity is fixed merely to hide missing intent."),
            ("Mistake: using Fix to stop motion. Recovery: remove Fix and add the geometric relationship that explains the location.", "Mistake: applying duplicate constraints. Recovery: inspect solver warnings and keep one clear relationship.", "Mistake: constraining circles to visible edges rather than stable references. Recovery: relate centers to construction geometry."),
            "Remove one symmetry constraint, observe the new freedom, then restore the relationship without adding a position dimension.",
            ("Perimeter orientation is constrained.", "Corners are coincident.", "Equivalent holes are equal.", "Functional centers use stable relationships.", "A drag test confirms intended behavior."),
            ("coincident", "concentric", "equal", "symmetric", "constraint solver"),
            (_check("Why is Fix weaker evidence of intent than symmetry?", "Fix freezes a position without explaining the relationship; symmetry states how paired geometry must behave."), _check("What should a drag test reveal before dimensions are complete?", "Only intentional size or spacing freedom should remain.")),
            (_media("images/academy/degrees-of-freedom.svg", "An unconstrained rectangle with arrows indicating translation and rotation freedoms.", "Geometric constraints remove unwanted movement before dimensions assign size."),),
        ),
        _lesson(
            "dimensions-fully-defined", "Dimensions and fully defined sketches",
            "Add the minimum independent dimensions needed to control size and verified interfaces.", 17,
            "Dimension the motor plate into a fully constrained sketch without redundant or conflicting controls.",
            "Fully constrained behavior makes manufacturing geometry predictable when FTC hardware or packaging values change.",
            ("Driving dimensions", "Reference dimensions", "Dimension schemes", "Redundancy", "Fully constrained sketch behavior"),
            ("Complete the geometrically constrained sketch.", "Confirm units and verified mounting dimensions before entering values."),
            (
                _step("Dimension the plate", "Add centered width and height dimensions using design-choice values.", "Centered dimensions preserve the origin strategy while controlling overall material size.", "Plate edges move equally about the origin when width or height changes."),
                _step("Dimension the mounting pitch", "Add the verified horizontal and vertical distances between mounting-hole centerlines.", "Center-to-center pitch should reflect the hardware interface directly.", "Hole centers remain symmetric and display the verified spacing."),
                _step("Dimension hole and clearance sizes", "Set mounting-hole diameter from the selected fastener strategy and motor clearance from verified hardware.", "Diameter values affect fit and must remain traceable to their purpose.", "All equal holes update from one controlling size and clear the selected hardware."),
                _step("Control edge material", "Express or measure the material from the outermost hole edge to the plate edge against the team minimum.", "Center-to-edge distance alone ignores hole radius and can overstate available material.", "The narrowest material meets the documented team requirement."),
                _step("Resolve remaining freedom", "Use solver color or status and drag tests to locate remaining degrees of freedom; add only the missing independent control.", "Adding dimensions blindly creates conflicts instead of explaining intent.", "The sketch reports fully constrained and does not move during a drag test."),
                _step("Classify dimensions", "Mark verification or reference dimensions as non-driving where appropriate and annotate their source.", "Reference values can prove a requirement without over-constraining the model.", "Driving and reference dimensions have distinct, explainable roles."),
            ),
            ("The solver reports fully constrained behavior.", "No redundant or conflicting-dimension warning remains.", "Mounting pitch and clearance trace to selected hardware.", "Minimum edge material is checked using the hole edge, not only its center."),
            ("Mistake: dimensioning every visible distance. Recovery: remove dependent dimensions and keep the smallest independent set.", "Mistake: entering hardware values without units or source. Recovery: confirm document units and annotate the specification table.", "Mistake: assuming a dark or locked-looking sketch is correct. Recovery: run a drag test and inspect each controlling dimension."),
            "Increase plate width without changing mounting pitch. Confirm the plate stays centered and calculate how edge material changes.",
            ("Width and height are centered controls.", "Mounting pitch uses verified values.", "Hole and clearance sizes are traceable.", "Minimum edge material passes.", "The sketch is fully constrained without conflicts."),
            ("driving dimension", "reference dimension", "fully constrained", "redundant constraint", "edge material"),
            (_check("Why not dimension both a symmetric hole's left and right offsets?", "Those offsets are dependent once symmetry and pitch are defined, so both can over-constrain the sketch."), _check("What does fully constrained prove?", "It proves no unintended sketch freedom remains; it does not prove the chosen dimensions are correct.")),
            (_media("images/academy/under-vs-fully-constrained.svg", "Side-by-side sketches showing geometry that can still move and geometry locked by origin, constraints, and dimensions.", "Fully constrained geometry has no unintended degrees of freedom, but its values still require verification."), _media("images/academy/safe-hole-edge.svg", "Two plate edges comparing a hole with adequate surrounding material and a hole placed too close to the edge.", "Measure minimum material from the hole edge, not just from its center.")),
        ),
        _lesson(
            "symmetry-patterns", "Symmetry, mirrors, and repeated hole patterns",
            "Create repeated mounting geometry while keeping one clear source of truth.", 15,
            "Use symmetry, Mirror, and sketch patterns to create editable repeated holes without duplicating independent dimensions.",
            "FTC motor and gearbox interfaces often repeat, but the method should preserve alignment and make exceptions deliberate.",
            ("Symmetry", "Mirror", linear_patterns, "Pattern count", "Seed geometry"),
            ("Open the fully constrained plate sketch.", "Confirm whether the selected mounting interface is mirrored, linearly repeated, circular, or a combination."),
            (
                _step("Choose the seed geometry", "Identify the smallest verified hole or hole group that can generate the intended pattern.", "A minimal seed prevents multiple circles from competing as independent sources of truth.", "One named group contains the controlling hole diameter and local relationships."),
                _step("Mirror across a centerline", "Use Mirror to create the opposite hole or group across construction geometry.", "Mirror preserves equality and opposite placement about a stable datum.", "Editing the seed location updates the mirrored result symmetrically."),
                _step("Create a linear repeat", f"Use a {linear_pattern} only where the hardware documentation specifies repeated equal spacing.", "A pattern captures count and spacing more clearly than copied entities.", "Changing pattern spacing updates every repeated center consistently."),
                _step("Create a circular repeat", "Use a circular pattern around the motor axis only if the verified pattern is angularly repeated.", "Circular repetition should follow hardware intent, not visual convenience.", "Instances share the verified center and angular relationship."),
                _step("Constrain the pattern location", "Relate the seed and pattern center to construction axes, then dimension only independent spacing or angle controls.", "Patterns repeat geometry but do not automatically prove the seed is correctly located.", "The complete pattern remains centered and fully constrained."),
                _step("Test pattern edits", "Change count or spacing temporarily, inspect edge material and overlaps, then restore or justify the valid configuration.", "Pattern tools can create geometrically valid but physically weak results.", "The accepted pattern has correct relationships and passes the material check."),
            ),
            ("The seed geometry is identifiable.", "Mirrored holes remain symmetric.", "Pattern count and spacing are explicit.", "The finished sketch remains fully constrained and passes edge-material checks."),
            ("Mistake: copying holes instead of relating them. Recovery: delete copies and rebuild from one seed with Mirror or a pattern.", "Mistake: patterning from the wrong center. Recovery: select the motor-axis datum as the circular center.", "Mistake: assuming every motor pattern is rectangular. Recovery: classify the verified interface before choosing a tool."),
            "Add a second optional two-hole pattern using a new seed and Mirror; keep it suppressed or clearly separated from the verified primary pattern.",
            ("One seed controls each repeated group.", "Mirror uses construction geometry.", "Pattern type matches hardware intent.", "Count and spacing are editable.", "Edge material remains acceptable."),
            ("seed geometry", "Mirror", "linear pattern", "rectangular pattern", "circular pattern", "instance count"),
            (_check("When is Mirror clearer than a two-instance pattern?", "When the core requirement is opposite placement about a known centerline."), _check("Does a sketch pattern guarantee safe hole placement?", "No. Count, spacing, and minimum edge material still require verification.")),
            (_media("images/academy/construction-symmetry.svg", "A plate with construction centerlines and mounting holes mirrored about its center.", "Mirror and symmetry use stable centerlines to preserve the plate center."),),
        ),
        _lesson(
            "parameters-expressions", "Variables or user parameters and expressions",
            "Promote important values into named controls and express useful dependencies.", 18,
            "Drive the plate, mounting pattern, edge material, and thickness with named parameters and readable expressions.",
            "Named controls let an FTC team adapt a mount without hunting through sketches or breaking linked clearances.",
            (parameter_title, "Expressions", "Units", "Dependencies", "Editable thickness"),
            ("Finish the fully constrained primary pattern.", "Have the specification table available so names reflect verified dimensions and design choices."),
            (
                _step(f"Create named {parameters}", ("Create variables for plateWidth, plateHeight, plateThickness, holeDiameter, horizontalPitch, verticalPitch, and minimumEdgeMaterial." if onshape else "Open Change Parameters and create user parameters for plateWidth, plateHeight, plateThickness, holeDiameter, horizontalPitch, verticalPitch, and minimumEdgeMaterial."), "A small named interface becomes the model's editable control panel.", f"All {parameters} have descriptive names, units, and documented sources."),
                _step("Replace literal sketch values", f"Edit driving dimensions so they reference the corresponding {parameter} by expression.", "A named value only controls the model after dimensions actually reference it.", "Changing horizontalPitch moves related holes without altering plate center."),
                _step("Express a safe plate size", "Where appropriate, express plate width or height from verified pitch, hole diameter, and twice the minimum edge material.", "A dependency can preserve material automatically when a hardware pattern changes.", "Changing pitch grows or shrinks the plate symmetrically while maintaining the intended margin."),
                _step("Drive editable thickness", f"Create the plate solid and reference plateThickness in its extrusion expression within the {context}.", "Thickness affects stiffness and packaging and should remain independent of sketch-plane dimensions.", "The finished plate changes thickness without changing its centered sketch."),
                _step("Test one dependency at a time", f"Change each key {parameter} separately and regenerate after every edit.", "Single-input tests identify the exact dependency that breaks a model.", "Each valid input produces a predictable update with a fully constrained sketch."),
                _step("Document input categories", f"Add descriptions or a nearby table marking each {parameter} as hardware-derived, measured, or a design choice.", "Names improve editability; provenance makes those edits trustworthy.", "A reviewer can tell which controls may change and which require hardware verification."),
            ),
            (f"Every important dimension references a named {parameter}.", "Thickness edits independently.", "The dependency expression preserves minimum material.", "A parameter test keeps the plate centered and sketch fully constrained."),
            (f"Mistake: creating {parameters} but leaving dimensions as literal numbers. Recovery: replace each literal with the named reference.", "Mistake: building a circular dependency. Recovery: identify one upstream requirement and make dependent values flow in one direction.", "Mistake: encoding an unverified hardware value as permanent. Recovery: label its source and verification state before reuse."),
            "Create a compact configuration by changing only named controls. Record which dependency reaches its safe limit first.",
            (f"Required controls are named {parameters}.", "Sketch dimensions use expressions.", "Thickness is editable.", "Dependencies flow in one direction.", "Every input has a provenance category."),
            ("parameter", "variable", "expression", "dependency", "unit-aware value", "circular dependency"),
            (_check("What is the difference between a named input and an expression?", "A named input stores a controlling value; an expression calculates a value from one or more controls."), _check("Why test one parameter at a time?", "It isolates failures and makes dependency behavior observable.")),
            (_media("images/academy/parameter-dependency.svg", "A flow diagram from verified motor dimensions and design choices through named parameters to sketch geometry and the finished plate.", "Dependencies should flow from verified inputs and design choices toward geometry without circular references."),),
        ),
        _lesson(
            "diagnose-repair-adapt", "Diagnose, repair, and adapt a broken sketch",
            "Use solver evidence and controlled tests to repair intent before adapting the plate to new verified hardware.", 17,
            "Diagnose a broken sketch, restore its intended relationships, and adapt the plate to a second verified mounting pattern without losing required invariants.",
            "Fast FTC iteration depends on repairing the cause of a sketch failure instead of freezing geometry or redrawing blindly.",
            ("Diagnosis", "Constraint conflicts", "Missing references", "Parameter tests", "Design invariants", "Adaptation"),
            ("Duplicate the completed plate as a safe practice version.", "Collect verified dimensions for a second motor or mounting pattern."),
            (
                _step("Create a controlled failure", "Remove one relationship or enter one conflicting dimension in the practice copy and observe the solver message and geometry behavior.", "A known failure teaches how the tool communicates under- and over-constraint.", "You can identify whether the sketch gained freedom or a conflict."),
                _step("Isolate the cause", "Inspect recent changes, constraint markers, and dimensions; suppress or undo one suspect item at a time.", "Changing one thing at a time preserves evidence and prevents secondary damage.", "One specific missing, duplicate, or conflicting control explains the failure."),
                _step("Repair the relationship", "Restore the constraint, reference, or expression that best states the original intent instead of using Fix.", "The repair should explain geometry and survive future edits.", "The sketch returns to fully constrained behavior without unexplained fixed entities."),
                _step("Enter the second verified interface", f"Create named {parameters} for the second motor values or update a clearly separated configuration using documented dimensions.", "Separating verified alternatives avoids silently overwriting the original evidence.", "The second interface has traceable hole size, spacing, and clearance controls."),
                _step("Adapt the pattern", "Revise the seed, Mirror, and pattern relationships for the second interface while keeping the plate center and symmetry fixed.", "Transfer proves the sketch encodes intent rather than one accidental shape.", "The second mounting pattern is correct, centered, symmetric, and fully constrained."),
                _step("Verify invariants", "Measure minimum edge material, test thickness, inspect hole relationships, and compare all preserved and changed parameters.", "A successful rebuild alone does not prove strength, fit, or design intent.", "The adaptation passes every stated invariant and the evidence distinguishes changed from fixed values."),
                _step("Explain the proof", "Write a short review naming documentation or measured dimensions, design choices, changed parameters, fixed relationships, and solver evidence.", "A teammate must understand both the result and why it can be trusted.", "The explanation connects each claim to a parameter, relationship, measurement, or fully constrained status."),
            ),
            ("The intentional failure is classified correctly.", "The repair restores intent without Fix.", "Second-interface values have verified sources.", "Plate center, symmetry, edge material, thickness, named controls, and hole relationships are preserved."),
            ("Mistake: deleting many constraints until the warning disappears. Recovery: undo, isolate one suspect change, and preserve unaffected intent.", "Mistake: replacing the original motor values without recording them. Recovery: keep a comparison table or explicit alternative parameter set.", "Mistake: accepting a successful rebuild as proof. Recovery: drag-test, measure edge material, and inspect every invariant."),
            CHALLENGE,
            ("I classified and repaired a sketch failure.", "Second-pattern values are verified.", "The plate center and symmetry remain fixed.", "Minimum edge material and thickness remain editable.", "Named parameters and hole relationships are correct.", "My explanation separates hardware inputs, design choices, changes, and invariants."),
            ("under-constrained", "over-constrained", "dangling reference", "invariant", "regeneration", "root cause"),
            (_check("What is the safest first response to a new solver conflict?", "Inspect the most recent change and isolate one suspect control at a time."), _check("What evidence proves preserved design intent?", "Stable datums, correct relationships, named controls, passing measurements, and fully constrained behavior together provide evidence.")),
            (_media("images/academy/under-vs-fully-constrained.svg", "A comparison between movable under-constrained geometry and a fully constrained centered pattern.", "Use solver status and drag tests together when diagnosing sketch freedom."), _media("images/academy/safe-hole-edge.svg", "Safe and weak examples of hole placement near a plate edge.", "Recheck minimum material after adapting any mounting pattern.")),
        ),
    )


def build_course(platform, pathway_name):
    lessons = lessons_for(platform)
    return {
        "slug": COURSE_SLUG, "platform": platform,
        "title": "Sketching and Parameters/Variables",
        "summary": "Build a configurable FTC motor-mounting plate from verified hardware dimensions and durable sketch relationships.",
        "level": "CAD Foundations", "difficulty": "Beginner",
        "duration_minutes": sum(lesson["estimated_minutes"] for lesson in lessons),
        "status": "Live",
        "outcome": "A configurable FTC motor-mounting plate with a fully constrained centered sketch, verified mounting pattern, editable thickness, named parameters, and documented design intent.",
        "prerequisites": ("Quick Start and CAD Mental Model",),
        "skills": ("Sketch planning", "Geometric constraints", "Fully constrained sketches", "Patterns and symmetry", "Parameters and diagnosis"),
        "tools": (pathway_name, "Documentation or measurements for two selected motor interfaces", "Selected fastener information"),
        "lessons": lessons,
        "brief": "Create and repair a stable motor-mounting plate whose geometry separates verified hardware requirements from team design choices.",
        "objectives": ("Plan sketches from stable datums and construction references.", "Constrain and dimension geometry without redundant controls.", "Build repeated mounting patterns from one source of truth.", "Drive geometry with named parameters and expressions.", "Diagnose failures and adapt the plate to a second verified interface."),
        "constraints": ("Do not assume a universal FTC motor pattern.", "Keep the plate centered and symmetric.", "Maintain the team's documented minimum edge material.", "Keep plate thickness editable and hardware values traceable."),
        "checkpoints": tuple(checkpoint for lesson in lessons for checkpoint in lesson["checkpoints"][:1]),
        "challenge": CHALLENGE, "artifacts": ARTIFACTS, "rubric": RUBRIC,
        "reference_specifications": REFERENCE_SPECIFICATIONS,
        "related": ("quick-start-cad-mental-model", "parts-components-ftc-libraries"),
        "equivalent_slug": COURSE_SLUG,
    }
