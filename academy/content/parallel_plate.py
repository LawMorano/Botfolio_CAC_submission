"""Parallel-Plate Drivetrain course content."""

COURSE_SLUG = "parallel-plate-drivetrain"

ENGINEERING_BRIEF = (
    "Design a compact, serviceable parallel-plate drivetrain for an FTC robot. "
    "Your CAD should make wheel placement, bearing support, motor mounting, and "
    "assembly clearance easy to inspect before any part is fabricated."
)
OBJECTIVES = (
    "Translate a robot envelope into a parameter-driven layout.",
    "Model two matching plates with serviceable wheel and motor interfaces.",
    "Constrain moving and fixed parts, then inspect fit and motion.",
    "Explain design choices with evidence in a portfolio artifact.",
)
CONSTRAINTS = (
    "Keep the complete drivetrain inside the team's current FTC robot size envelope; verify the current season rules before building.",
    "Allow clearance for wheels, fasteners, bearings, motors, wiring, and assembly tools.",
    "Use dimensions from the actual components your team selects; provisional dimensions must be labeled for later verification.",
    "Show a plausible way to manufacture, assemble, and replace a damaged plate.",
)
CHALLENGE = (
    "Revise your drivetrain for a wider wheel while keeping its outer envelope fixed. "
    "Show what moved, what clearance became tighter, and why your final spacing is defensible."
)
ARTIFACTS = (
    "A view of the complete assembly and one plate with dimensions or annotations.",
    "A short parameter table listing envelope, track width, wheel diameter, and plate spacing.",
    "A clearance or motion check and a note explaining one issue you found and fixed.",
    "A brief reflection on manufacturing, service access, and the wider-wheel revision.",
)
RUBRIC = (
    {"criterion": "Envelope and parameters", "evidence": "Named dimensions drive a symmetric layout inside the stated envelope."},
    {"criterion": "Interfaces and assembly", "evidence": "Plate features align with selected hardware and fixed and moving parts are constrained sensibly."},
    {"criterion": "Verification", "evidence": "Clearance, motion, and service access are checked and one revision is explained."},
    {"criterion": "Communication", "evidence": "The published artifact lets another builder understand dimensions, choices, and remaining assumptions."},
)

REFERENCE_SPECIFICATIONS = (
    "Wheel diameter and width", "Bearing outside diameter and width", "Shaft diameter",
    "Motor mounting pattern", "Motor body envelope", "Fastener diameter",
    "Plate thickness", "Planned plate spacing", "Maximum drivetrain envelope",
)


def _step(title, action, reason, result, note=""):
    return {"title": title, "action": action, "reason": reason, "result": result, "note": note}


def _lesson(identifier, title, summary, minutes, outcome, relevance, concepts, setup,
            steps, checkpoints, mistakes, practice, checklist, media=()):
    return {
        "id": identifier, "title": title, "summary": summary,
        "estimated_minutes": minutes, "outcome": outcome, "ftc_relevance": relevance,
        "concepts": concepts, "required_setup": setup, "steps": steps,
        "checkpoints": checkpoints, "common_mistakes": mistakes,
        "practice": practice, "completion_checklist": checklist,
        "vocabulary": (), "reference_specifications": REFERENCE_SPECIFICATIONS,
        "media": media,
        "self_check": ({"question": "What evidence demonstrates this lesson's outcome?", "answer": outcome},),
    }


def lessons_for(platform):
    onshape = platform == "onshape"
    product = "Onshape" if onshape else "Fusion 360"
    param = "variables" if onshape else "user parameters"
    modeling_context = "Part Studio" if onshape else "drivetrain component"
    fixed_constraint = "Fastened mates" if onshape else "rigid joints or a rigid group"
    rotating_constraint = "Revolute mates" if onshape else "revolute joints"

    return (
        _lesson(
            "brief", "Establish the design brief and robot envelope",
            "Turn team requirements and measured hardware into a traceable drivetrain specification.", 28,
            "Create a labeled specification table and a parameter-driven maximum drivetrain envelope.",
            "The drivetrain consumes much of an FTC robot's legal and practical packaging space; early assumptions affect every subsystem.",
            ("Requirements", "Provisional values", "Hardware specifications", "Robot envelope", param.title()),
            (f"Create a new {product} drivetrain workspace.", "Collect datasheets or measurements for the team's selected hardware; do not rely on generic FTC dimensions."),
            (
                _step("Write the design brief", "Record the intended wheel count, drive style, service goals, manufacturing process, and maximum allocated envelope.", "A model cannot resolve unstated tradeoffs, and the current game may change packaging priorities.", "The brief states measurable needs and distinguishes them from preferences."),
                _step("Build the specification table", "Record every reference-specification field, its source, unit, and verification state; label unknowns provisional.", "Traceable values prevent a plausible-looking model from silently using the wrong hardware.", "Every required field has a sourced value or a clearly marked placeholder."),
                _step("Create named controls", ("Create variables for maximum length, maximum width, plate spacing, plate thickness, wheel diameter, and wheel width." if onshape else "Create user parameters for maximum length, maximum width, plate spacing, plate thickness, wheel diameter, and wheel width."), "Named controls expose the packaging decisions that later geometry must follow.", "The parameter list uses consistent units and descriptive names."),
                _step("Sketch the allocated envelope", f"In the {modeling_context}, create a centered top-view envelope driven by the maximum length and width controls.", "A centered datum makes left-right symmetry and later assembly checks easier.", "A constrained rectangle represents the team's allocated drivetrain volume."),
                _step("Mark hard and soft boundaries", "Add construction zones for frame limits, wheel sweep, wiring, and required tool access; annotate which boundaries may still change.", "Not every clearance has the same certainty or consequence.", "The sketch distinguishes immutable constraints from provisional packaging reserves."),
            ),
            ("The envelope is centered and driven by named controls.", "All reference fields include a source or provisional label.", "No dimension is presented as a universal FTC standard."),
            ("Mistake: copying dimensions from another robot. Recovery: replace them with selected-hardware data and cite the source.", "Mistake: treating the legal robot limit as the subsystem target. Recovery: document the smaller envelope allocated by the team.", "Mistake: hiding unknowns. Recovery: label them provisional and add a verification owner or date."),
            "Reduce the allocated width by a small, realistic amount for another subsystem. Identify which controls and risks change.",
            ("The design brief is measurable.", "All required hardware fields are recorded.", "Unknowns are provisional.", "Named controls drive the envelope.", "Clearance zones are visible."),
            media=("Needed asset: drivetrain specification-table example; not yet available.",),
        ),
        _lesson(
            "layout", "Create the master layout sketch",
            "Arrange wheel centers, motor axes, plate references, and clearances from one symmetric source of truth.", 35,
            "Create a fully constrained master layout that updates symmetrically when drivetrain controls change.",
            "The master layout lets an FTC team test packaging before investing time in detailed parts.",
            ("Skeleton modeling", "Centerlines", "Symmetry", "Wheel sweep", "Design intent"),
            ("Complete the reference table and envelope lesson.", f"Open the drivetrain {modeling_context} and display the named {param}."),
            (
                _step("Establish datums", "Add longitudinal and transverse construction centerlines through the origin.", "Stable datums provide references for symmetry, axles, and plate placement.", "Both axes are construction geometry and fixed by the origin."),
                _step("Place wheel axes", "Place wheel centers from the selected wheel count and constrain paired positions symmetrically about the robot center.", "Symmetry prevents left and right geometry from drifting independently.", "A track-width edit moves paired centers equally in opposite directions."),
                _step("Represent wheel sweep", "Draw construction circles or envelopes using selected wheel diameter and width.", "Wheel centers alone do not reveal frame, floor, or neighboring-wheel collisions.", "Every wheel axis has a visible swept-volume reference."),
                _step("Place motor envelopes", "Add simplified motor body and shaft-axis references from the recorded motor envelope and mounting relationship.", "Motor bodies, wires, and output alignment often control usable plate space.", "Each motor reference has a source dimension and a plausible power-transfer path."),
                _step("Locate plates and service zones", "Define inside and outside plate faces from plate spacing and thickness, then reserve access around fasteners and removable hardware.", "Nominal fit is insufficient if tools cannot reach fasteners or components cannot be replaced.", "Plate faces update from spacing and thickness, and service zones do not collide with the envelope."),
                _step("Test the layout", "Change track width and one provisional hardware value separately, then inspect symmetry and clearance.", "A master layout is valuable only if it survives expected requirement changes.", "The sketch rebuilds without unconstrained drift or broken relationships."),
            ),
            ("Wheel centers mirror about the drivetrain center.", "Wheel and motor envelopes use selected-hardware values.", "Plate spacing updates both plate references predictably.", "The layout remains fully constrained after a test edit."),
            ("Mistake: dimensioning mirrored wheel centers separately. Recovery: use symmetry or mirror relationships around a centerline.", "Mistake: drawing only ideal axes. Recovery: add full wheel and motor envelopes.", "Mistake: constraining details to projected edges that may disappear. Recovery: reference stable datums and master geometry."),
            "Increase the required front clearance for an intake. Rebalance axle positions and explain the resulting wheelbase tradeoff.",
            ("Datums are origin-based.", "Wheel locations are symmetric.", "Hardware envelopes are visible.", "Plate and service zones are represented.", "The layout passes a parameter-change test."),
            media=("Needed asset: annotated master-layout checkpoint image; not yet available.",),
        ),
        _lesson(
            "plates", "Model the two drivetrain plates",
            "Turn shared layout geometry into two manufacturable, editable plates.", 38,
            "Create matching drivetrain plates that remain aligned and manufacturable after parameter changes.",
            "Shared plate logic reduces mismatched holes while allowing deliberate differences for motors, wiring, and service access.",
            ("Shared geometry", "Plate thickness", "Manufacturing intent", "Feature order", "Symmetric parts"),
            ("Complete and fully constrain the master layout.", "Confirm the team's intended plate material and manufacturing process."),
            (
                _step("Define the plate perimeter", "Reference stable master-layout geometry to sketch a plate outline with intentional material around interfaces.", "The outline should respond to packaging controls without inheriting every fragile edge.", "A closed, constrained perimeter fits inside the allocated envelope."),
                _step("Create the first plate", ("Extrude the perimeter as a new left-plate part in the Part Studio using the plate-thickness variable." if onshape else "Extrude the perimeter as a new body inside an active Left Plate component using the plate-thickness user parameter."), "Explicit ownership and thickness make the plate reusable and inspectable.", "One named plate has the intended thickness and no extra bodies."),
                _step("Create the matching plate", ("Create the right plate as a second part from the same master references, offset by the plate-spacing variable." if onshape else "Create a Right Plate component from the same master references and position it from the plate-spacing user parameter."), "Both plates should share controlling intent rather than duplicate independent sketches.", "The second plate aligns with the first and updates when spacing changes."),
                _step("Add structural cutouts cautiously", "Add only cutouts justified by clearance or mass goals, retaining load paths around bearings, motors, and fasteners.", "Removing material without considering force flow creates attractive but weak plates.", "Cutouts avoid interface zones and leave continuous structural paths."),
                _step("Add manufacturing edge treatments", "Apply only fillets, chamfers, or corner radii compatible with the planned process, after structural geometry is stable.", "Tool radius and fabrication method constrain achievable corners.", "Edge details are manufacturable and appear late in the feature history."),
                _step("Verify paired updates", "Change plate spacing and thickness one at a time, then compare plate alignment and envelope compliance.", "Shared geometry must survive realistic packaging revisions.", "Both named plates remain aligned and inside the allocated envelope."),
            ),
            ("Two separately identifiable plates exist.", "Both use the named thickness and shared layout references.", "Cutouts preserve material around high-load interfaces.", "A spacing edit does not break alignment."),
            ("Mistake: duplicating an independent plate sketch. Recovery: derive both plates from stable master references.", "Mistake: leaving bodies unorganized in Fusion. Recovery: place each plate body in its intended component.", "Mistake: maximizing cutouts before interface loads are known. Recovery: suppress decorative cutouts and restore conservative load paths."),
            "Change the manufacturing process from machined plate to a process with a larger minimum inside radius. Revise one cutout accordingly.",
            ("Both plates are named and organized.", "Thickness and spacing are parametric.", "Plate outlines are manufacturable.", "Load paths remain around interfaces.", "The paired update test passes."),
        ),
        _lesson(
            "interfaces", "Add wheel, bearing, shaft, and motor interfaces",
            "Build selected-hardware interfaces with traceable dimensions and service access.", 42,
            "Add aligned bearing, shaft, wheel, motor, and fastener interfaces to both plates and verify their support paths.",
            "Small interface errors can make FTC hardware impossible to assemble, retain, or replace even when the overall layout fits.",
            ("Fits and clearances", "Bearing support", "Shaft axes", "Motor patterns", "Fastener access"),
            ("Verify selected hardware specifications against current datasheets or measurements.", "Complete the paired plate model."),
            (
                _step("Create bearing seats", "Place bearing-seat geometry on the wheel axes using the selected bearing outside diameter and width; record the intended fit rather than assuming it.", "Bearing retention depends on real hardware and manufacturing tolerance.", "Every bearing seat is concentric with a wheel axis and traceable to the specification table."),
                _step("Represent shafts and wheels", ("Create simplified shaft and wheel parts and place mate connectors on their true axes." if onshape else "Create simplified Shaft and Wheel components and place joint origins on their true axes."), "Simplified hardware is sufficient for collision and alignment checks when its critical dimensions are accurate.", "Shafts pass through aligned supports and wheels occupy their recorded width."),
                _step("Add motor interfaces", "Create the selected motor mounting pattern, output-axis reference, and body envelope from verified specifications.", "Bolt holes alone do not prove that the motor body, shaft, and transmission path fit.", "The motor axis aligns with the intended drive path and its body clears both plates."),
                _step("Add fastener holes", "Place fastener holes using the selected diameter and reserve head, nut, washer, and tool-access volumes.", "Assembly access is a design requirement, not a workshop afterthought.", "Fasteners have visible retention and tool paths without collisions."),
                _step("Propagate shared interfaces", "Use shared references or deliberate patterns to align interfaces across the two plates; keep asymmetric motor or service features explicit.", "Automatic symmetry is useful only where the physical requirement is symmetric.", "Paired holes share axes while deliberate left-right differences remain understandable."),
                _step("Audit material and support", "Measure minimum material around every hole and trace load paths from wheels and motors into the plates and cross-structure.", "Interfaces need enough surrounding structure to carry impact and drive loads.", "No interface floats, breaks an edge, or lacks a plausible support path."),
            ),
            ("Bearing seats and shafts are concentric across their supports.", "Motor pattern and body envelope come from selected hardware.", "Fastener and tool access is visible.", "Minimum material around interfaces is measured against a team requirement."),
            ("Mistake: using nominal bearing diameter as a universal finished fit. Recovery: document material, process, and intended fit before final sizing.", "Mistake: modeling mounting holes without the motor body. Recovery: add its verified envelope and connector clearance.", "Mistake: mirroring an intentionally handed interface. Recovery: separate shared axes from side-specific features."),
            "Swap to a different selected fastener diameter. Update its clearance and tool envelope, then identify every affected feature.",
            ("Bearing, shaft, wheel, and motor references are traceable.", "Interfaces align across plates.", "Fasteners are installable and removable.", "Material checks are recorded.", "Side-specific features are intentional."),
            media=("Needed asset: interface stack-up and tool-access diagram; not yet available.",),
        ),
        _lesson(
            "assembly", "Assemble, constrain, inspect, and review the drivetrain",
            "Create realistic fixed and rotating relationships, then use inspection evidence to drive a revision.", 37,
            "Produce and review a drivetrain assembly with credible motion, clearance, service access, and a documented revision.",
            "FTC drivetrains fail at interfaces: collision, over-constraint, inaccessible fasteners, and underestimated component width.",
            ("Assembly constraints", "Degrees of freedom", "Interference", "Section inspection", "Service review"),
            ("Finish the two plates and simplified hardware interfaces.", "Resolve or label every provisional value that affects assembly fit."),
            (
                _step("Start the assembly", ("Insert the plates and simplified hardware into an Assembly; fix one intentional base reference." if onshape else "Create an assembly context with the drivetrain components and ground one intentional base component."), "One grounded reference prevents drift without masking incorrect relationships elsewhere.", "The assembly has one clear datum and components remain individually identifiable."),
                _step("Constrain fixed hardware", f"Apply {fixed_constraint} to plates, spacers, bearings, and motor hardware that should not move relative to its support.", "Fixed relationships represent clamped or retained hardware and remove only intended freedom.", "Fixed hardware does not drift during drag tests."),
                _step("Preserve wheel rotation", f"Apply {rotating_constraint} on the verified wheel or shaft axes and test rotation.", "A drivetrain review needs the intended rotational degree of freedom.", "Wheels rotate about aligned axes without translating or dragging the frame."),
                _step("Inspect sections and interference", "Use section and interference tools to inspect bearing support, shaft passage, wheel-to-plate clearance, motor clearance, and fastener stacks.", "Visual exterior review misses internal overlap and unsupported gaps.", "The review produces concrete pass/fail observations for each critical interface."),
                _step("Perform a service sequence", "Describe and simulate the order for removing one wheel, motor, and damaged plate using available tool paths.", "A working assembly can still be impractical to maintain between FTC matches.", "The sequence identifies accessible fasteners and any component that traps another."),
                _step("Complete the wider-wheel challenge", "Increase wheel width while holding the outer envelope fixed, revise plate spacing or internal placement, and document the tightest clearance.", "This transfer task tests whether the model exposes real packaging tradeoffs.", "The assembly rebuilds, rotates, and includes a defensible before-and-after explanation."),
            ),
            ("Exactly the intended rotating degrees of freedom remain.", "Section and interference checks cover every hardware interface.", "A wheel, motor, and plate have plausible service paths.", "The wider-wheel revision stays inside the stated outer envelope."),
            ("Mistake: fixing every component until the assembly appears stable. Recovery: retain only one base reference and rebuild relationships by function.", "Mistake: assuming free rotation proves clearance. Recovery: inspect the full wheel width and fastener stack through its swept space.", "Mistake: reporting only 'no interference.' Recovery: record the tested configuration, tightest clearance, and unresolved assumptions."),
            CHALLENGE,
            ("Fixed and rotating relationships match physical intent.", "Wheel motion is verified.", "Internal interfaces were sectioned and checked.", "The service sequence is documented.", "The wider-wheel revision and tightest clearance are explained."),
            media=("Needed asset: final assembly checkpoint and section-view images; not yet available.",),
        ),
    )


def build_course(platform, pathway_name):
    lessons = lessons_for(platform)
    return {
        "slug": COURSE_SLUG, "platform": platform,
        "title": "Parallel-Plate Drivetrain",
        "summary": "Design, assemble, and review a serviceable FTC drivetrain.",
        "level": "Mechanism Labs", "difficulty": "Intermediate",
        "duration_minutes": sum(lesson["estimated_minutes"] for lesson in lessons),
        "status": "Live",
        "outcome": "A parameter-driven, reviewed drivetrain assembly and a portfolio-ready design explanation.",
        "prerequisites": ("Quick Start and CAD Mental Model", "Sketching and Parameters/Variables", "Parts or Components and FTC Libraries", "Assemblies and Motion"),
        "skills": ("Parametric layout", "Hardware interfaces", "Motion and clearance review", "Design communication"),
        "tools": (pathway_name, "Chosen FTC wheel, bearing, shaft, motor, and fastener specifications"),
        "lessons": lessons, "brief": ENGINEERING_BRIEF, "objectives": OBJECTIVES,
        "constraints": CONSTRAINTS,
        "checkpoints": tuple(checkpoint for lesson in lessons for checkpoint in lesson["checkpoints"][:1]),
        "challenge": CHALLENGE, "artifacts": ARTIFACTS, "rubric": RUBRIC,
        "reference_specifications": REFERENCE_SPECIFICATIONS,
        "related": ("assemblies-and-motion", "robot-integration-strategy"), "equivalent_slug": COURSE_SLUG,
    }
