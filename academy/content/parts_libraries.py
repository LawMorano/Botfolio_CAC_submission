"""Parts or Components and FTC Libraries foundation course content."""

COURSE_SLUG = "parts-components-ftc-libraries"

CHALLENGE = (
    "Replace one major COTS component in the wheel-module kit with a different verified option "
    "while preserving the custom interface part's design intent. Explain which source and critical "
    "dimensions changed, which named parameters were updated, which geometry remained stable, "
    "whether the custom interface still works, and what must be checked during Assemblies and Motion."
)

ARTIFACTS = (
    "A reusable wheel-module kit containing verified wheel, bearing, shaft, spacer, and motor-envelope references.",
    "A source record for every COTS item with manufacturer, part number, URL, date or revision, units, confidence, and verification notes.",
    "One custom parametric interface part using verified inputs and explicitly labeled design clearances.",
    "A lightweight representation set preserving critical axes, faces, holes, seats, diameters, and collision envelopes.",
    "A before-and-after substitution review for a second verified major COTS option.",
)

RUBRIC = (
    {"criterion": "Source quality", "evidence": "Every COTS reference has traceable provenance, units, critical dimensions, confidence, and verification status."},
    {"criterion": "Reference usefulness", "evidence": "Simplified geometry preserves accurate interfaces and axes while omitting irrelevant detail."},
    {"criterion": "Custom interface", "evidence": "Named controls separate factual hardware dimensions from chosen clearance, tolerance, wall, and edge values."},
    {"criterion": "Reuse and revision", "evidence": "The kit is organized for later assembly and survives a documented substitution without losing design intent."},
)

SOURCE_FIELDS = (
    "Manufacturer", "Part number", "Source URL", "Revision or retrieval date", "Units",
    "Critical dimensions", "Confidence level", "Dimensions requiring physical verification",
)

REFERENCE_SPECIFICATIONS = SOURCE_FIELDS + (
    "Wheel diameter and width", "Bearing outside diameter, inside diameter, and width",
    "Shaft diameter", "Spacer length and bore", "Motor mounting and body envelope",
    "Selected interface clearance", "Selected wall and edge material",
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
    body_term = "part" if onshape else "body"
    parameter = "variable" if onshape else "user parameter"
    parameters = "variables" if onshape else "user parameters"

    return (
        _lesson(
            "plan-part-structure", "Plan the part structure",
            "Assign clear responsibilities to reusable COTS references, custom geometry, and the later assembly.", 17,
            "Plan a wheel-module kit whose parts, reference axes, origins, and assembly responsibilities are explicit.",
            "Good structure lets an FTC team replace a wheel, bearing, shaft, or motor without rebuilding unrelated geometry.",
            (("Documents", "Tabs", "Part Studios", "Parts", "Multi-part Part Studios", "COTS and custom parts") if onshape else
             ("Projects", "Designs", "Components", "Bodies", "Component origins", "COTS and custom parts")),
            (f"Open {product} and create a workspace for an FTC wheel-module kit.", "Choose a real wheel-module concept without assuming any universal hardware size."),
            ((
                _step("Map the responsibilities", "List the wheel, bearing, shaft, spacer, motor envelope, custom interface, and future assembly as separate responsibilities.", "A part should define reusable geometry; an assembly should define placement and motion.", "Each item has one stated purpose and an owner in the model structure."),
                _step("Create the document and tabs", "Create a clearly named Document with a source-notes tab, a COTS Reference Part Studio, a Custom Interface Part Studio, and an Assembly placeholder tab.", "Tabs separate source evidence, modeling, and assembly contexts without scattering the kit across uncontrolled documents.", "The tab names reveal where references, custom work, and later assembly belong."),
                _step("Choose single- or multi-part responsibility", "Use a multi-part Part Studio only for closely related custom geometry sharing stable references; keep unrelated COTS references independently identifiable.", "Multi-part design is powerful when parts share intent but confusing when it creates accidental dependencies.", "Every Part Studio has a short written reason for containing one or several Parts."),
                _step("Assign origins and axes", "Define a wheel or shaft axis and a mounting-face origin convention for every proposed Part.", "Consistent origins reduce mate setup and orientation repair later.", "All proposed Parts use the same axis direction and comparable mounting-face reference."),
                _step("Mark COTS and custom ownership", "Label purchased COTS geometry read-only reference and the interface part team-controlled custom geometry.", "Purchased shape should not be casually redesigned, while custom geometry must remain editable.", "The plan makes edit authority and verification responsibility obvious."),
            ) if onshape else (
                _step("Map the responsibilities", "List the wheel, bearing, shaft, spacer, motor envelope, custom interface, and future assembly as separate responsibilities.", "A component should own reusable geometry; assembly relationships should define placement and motion.", "Each item has one stated purpose and an owner in the model structure."),
                _step("Create the project and design", "Create a clearly named Project and Design, then create top-level Components for COTS References and Custom Interface.", "Projects organize related Designs while Components provide reusable ownership inside them.", "The Browser shows intentional Components rather than a flat collection of Bodies."),
                _step("Put bodies in components", "Plan one component per independently reusable item and keep each Body inside its owning Component.", "A loose Body lacks its own reusable origin and assembly identity.", "Every planned Body has a named Component owner."),
                _step("Assign component origins", "Define a wheel or shaft axis and mounting-face origin convention for every proposed Component.", "Consistent component origins reduce joint setup and orientation repair later.", "All proposed Components use the same axis direction and comparable mounting-face reference."),
                _step("Mark COTS and custom ownership", "Label purchased COTS Components read-only reference and the interface Component team-controlled custom geometry.", "Purchased shape should not be casually redesigned, while custom geometry must remain editable.", "The plan makes edit authority and verification responsibility obvious."),
            )),
            ("The kit plan separates part definition from later assembly placement.", "Every reusable item has an owner, origin, and primary axis.", "COTS and custom responsibilities are labeled."),
            ("Mistake: putting the whole module in one indistinguishable object. Recovery: separate independently replaceable responsibilities.", "Mistake: treating a loose body as a component in Fusion. Recovery: create and activate an owning Component.", "Mistake: choosing origins after modeling. Recovery: define interface faces and axes before importing or building geometry."),
            "Add a second wheel option to the plan and identify what should remain a shared interface versus a separate reference.",
            ("Part and assembly responsibilities are separated.", "COTS and custom items are identified.", "The platform structure is named.", "Origins and axes follow one convention.", "The proposed kit can accept a replacement item."),
            ("COTS", "custom part", "part", "component", "body", "origin", "axis", "assembly responsibility"),
            (_check("Where should wheel rotation be defined?", "In the later assembly relationship, not baked into the reusable wheel geometry."), _check("Why give every reusable item a consistent axis?", "It makes later placement, replacement, and motion relationships predictable.")),
            (_media("images/academy/bodies-vs-components.svg", "A comparison of loose unlabeled solids with organized reusable parts or components, each with a clear owner.", "Reusable geometry needs intentional ownership rather than a flat pile of solids."), _media("images/academy/origin-axis-consistency.svg", "Wheel, bearing, shaft, spacer, and motor envelope aligned to a shared horizontal axis and consistent mounting-face origins.", "Consistent axes and origins reduce assembly work later.")),
        ),
        _lesson(
            "verify-cots-hardware", "Find and verify COTS hardware",
            "Create defensible source records before trusting downloaded or community geometry.", 18,
            "Produce complete provenance records and a verification plan for the selected wheel, bearing, shaft, spacer, and motor.",
            "A visually similar FTC component can differ by revision, units, mounting features, or fit-critical dimensions.",
            ("Manufacturer documentation", "Approved CAD libraries", "Physical measurement", "Provenance", "Confidence levels"),
            ("Choose actual hardware your team can document or measure.", "Prepare a table with every required source field."),
            (
                _step("Identify each exact product", "Record manufacturer and part number for every COTS item; treat unknown identity as provisional.", "Product category or appearance cannot distinguish revisions and variants.", "Each item has an exact identifier or a visible provisional warning."),
                _step("Capture source and date", "Record the source URL and revision or retrieval date without requiring any particular vendor.", "Sources change; date and revision make later re-verification possible.", "A teammate can return to the evidence used for each reference."),
                _step("Record units and critical dimensions", "List source units and only the dimensions needed for axes, faces, holes, seats, shafts, and collision envelopes.", "Critical interfaces deserve precision while decorative detail does not.", "Every modeled interface maps to a documented dimension and unit."),
                _step("Assign confidence", "Rate each value as manufacturer-verified, approved-library, physically measured, community-unverified, or provisional.", "Confidence makes uncertainty actionable rather than hidden.", "Low-confidence values are visibly separated from verified inputs."),
                _step("Plan physical verification", "Mark dimensions that require calipers, gauges, or fit checks on the team's actual hardware.", "Even authoritative documents can omit tolerance, coating, or revision details.", "Each fit-critical unknown has a specific physical check."),
                _step("Reject weak evidence", "Flag visual matches, unsourced community models, wrong revisions, unit ambiguity, missing mounting features, and unnecessarily detailed files.", "A polished model is not dimensional proof and may slow every downstream design.", "No reference is accepted solely because it looks correct."),
            ),
            ("Every COTS item has all eight provenance fields.", "Critical dimensions include units and confidence.", "Physical checks are assigned where documentation is insufficient."),
            ("Mistake: accepting a community model with no provenance. Recovery: locate documentation or measure the physical item.", "Mistake: overlooking a product revision. Recovery: compare exact part numbers and revision dates.", "Mistake: treating a visual match as proof. Recovery: compare documented critical dimensions numerically."),
            "Compare two possible sources for one item and justify which is stronger using provenance and confidence rather than appearance.",
            ("Manufacturer and part number are recorded.", "Source and date or revision are recorded.", "Units and critical dimensions are explicit.", "Confidence is assigned.", "Physical verification needs are listed."),
            ("provenance", "revision", "retrieval date", "confidence level", "critical dimension", "physical verification"),
            (_check("Does a visually identical CAD model prove fit?", "No. Exact identity, units, revision, and critical dimensions still require verification."), _check("When should a dimension remain provisional?", "When its source is weak, ambiguous, missing, or still requires physical confirmation.")),
            (_media("images/academy/cots-verification-flow.svg", "A flow from product identity through source, units, critical dimensions, confidence, and physical verification to an approved reference.", "Accept COTS geometry only after its evidence and remaining uncertainty are explicit."),),
        ),
        _lesson(
            "import-inspect-reference", "Import and inspect reference geometry",
            "Bring interchange geometry into the kit and prove that its scale and interfaces match the source record.", 18,
            "Import, organize, measure, orient, and assess a COTS reference against documented critical dimensions.",
            "Incorrect import units or orientation can silently corrupt every clearance and assembly relationship in an FTC mechanism.",
            ("STEP interchange", "Import units", "Measurement", "Orientation", "Reference inspection"),
            (("Choose one appropriate STEP or other supported interchange file and open the kit Document.",) if onshape else ("Choose one appropriate STEP or other supported interchange file and open the kit Project.",)),
            ((
                _step("Import into the document", "Import the file into the Document and identify the generated import tab and resulting Part Studio or part data.", "Keeping imports in identifiable tabs preserves source context and avoids mixing them with custom features.", "The imported geometry has a dedicated, clearly named location."),
                _step("Confirm units", "Inspect import settings and measure one documented overall dimension in the Part Studio.", "A unit mismatch can scale valid geometry by a large factor.", "The measured value agrees with the source record in the intended unit."),
                _step("Inspect orientation and origin", "Show principal planes and axes; compare the imported wheel or shaft axis with the kit convention.", "Orientation determines how easily the Part can be inserted and mated later.", "Axis direction and mounting face are documented, even if reorientation is needed."),
                _step("Rename the imported part and tab", "Use manufacturer, part number, function, and verification state in concise names.", "Default filenames and Part names lose meaning when several options are present.", "The tab and Part can be identified without opening source notes."),
                _step("Measure critical features", "Measure axes, mounting faces, holes, bearing seats, shaft diameters, and collision envelope values that matter for the selected item.", "The model must be checked against evidence, not trusted because import succeeded.", "Every critical measurement agrees or is recorded as a discrepancy."),
                _step("Mark irrelevant detail", "Identify threads, logos, tiny chamfers, internal electronics, or decorative surfaces that do not affect interfaces.", "Unnecessary detail slows documents and obscures functional geometry.", "The review separates keep-critical features from simplify candidates."),
            ) if onshape else (
                _step("Upload the interchange file", "Upload the file into the Project, open the resulting Design, and identify its Components and Bodies.", "A controlled project location preserves source context and avoids anonymous local copies.", "The uploaded Design has a clear source-aware name."),
                _step("Insert or reference it intentionally", "Insert the Design into the kit or keep it as a linked reference where appropriate; avoid copying loose Bodies.", "Component ownership and links preserve reusable identity and revision awareness.", "The kit contains an identifiable Component rather than an uncontrolled duplicate Body."),
                _step("Confirm units", "Measure one documented overall dimension immediately after upload or insertion.", "A unit mismatch can scale valid geometry by a large factor.", "The measured value agrees with the source record in the intended unit."),
                _step("Inspect orientation and origin", "Show the Component origin and compare the wheel or shaft axis with the kit convention.", "Component origins determine later joint placement and replacement behavior.", "Axis direction and mounting face are documented, even if reorientation is needed."),
                _step("Rename and measure", "Rename the Component and Bodies, then measure critical axes, faces, holes, seats, diameters, and envelope dimensions.", "Names preserve identity; measurements prove the reference matches evidence.", "Critical values agree with the source record or have recorded discrepancies."),
                _step("Mark irrelevant detail", "Identify threads, logos, tiny chamfers, internal electronics, or decorative surfaces that do not affect interfaces.", "Unnecessary detail slows Designs and obscures functional geometry.", "The review separates keep-critical features from simplify candidates."),
            )),
            ("One documented measurement confirms import scale.", "Orientation and origin are compared with the kit convention.", "Critical features match the source or have discrepancies recorded."),
            ("Mistake: assuming STEP embeds the intended units correctly. Recovery: measure a documented feature immediately.", "Mistake: renaming only the file. Recovery: rename the internal Part, Component, or Body too.", "Mistake: moving geometry without documenting the original axis. Recovery: record source orientation before reorientation."),
            "Import or inspect a second simple reference and decide whether its orientation can follow the same origin convention.",
            ("The import has a controlled location.", "Units are measured.", "Names identify the exact item.", "Origin and axis are documented.", "Critical dimensions are compared.", "Irrelevant detail is listed."),
            ("STEP", "interchange format", "import scale", "orientation", "source geometry", "model discrepancy"),
            (_check("What is the first dimensional check after import?", "Measure a known documented feature to confirm units and scale."), _check("Why retain a discrepancy instead of adjusting geometry silently?", "A discrepancy may reveal the wrong revision or weak source and must remain traceable.")),
        ),
        _lesson(
            "simplified-representations", "Create simplified representations",
            "Preserve functional interfaces while removing geometry that does not support fit, motion, or collision review.", 18,
            "Create lightweight wheel, bearing, shaft, spacer, and motor-envelope references with accurate critical interfaces.",
            "Lightweight FTC assemblies regenerate faster and make interface errors easier to see.",
            ("Simplification", "Collision envelopes", "Accurate interfaces", "Axes and mounting faces", "Model complexity"),
            ("Finish the import inspection and keep an untouched source reference.", "List critical geometry for each wheel-module item."),
            (
                _step("Preserve the source", "Keep the verified import unchanged and create a clearly linked or traceable simplified representation.", "An untouched reference allows later re-checking and prevents simplification from erasing provenance.", "Source and simplified geometry are distinct and cross-referenced."),
                _step("Simplify the wheel", "Retain overall diameter, width, bore or hub interface, axis, and collision envelope; omit tread texture and branding.", "Wheel sweep and shaft fit matter while decorative tread detail rarely changes packaging.", "The light wheel matches all documented critical dimensions."),
                _step("Simplify bearing and shaft", "Retain bearing outside diameter, bore, width, seats, shaft diameter, length envelope, and common axis.", "Concentric fit and support width control function.", "Bearing and shaft align concentrically with measurable critical sizes."),
                _step("Simplify the spacer", "Retain bore, length, end faces, and axis; remove cosmetic edge or surface detail.", "Spacer length controls stack-up while decorative features do not.", "The spacer has accurate axial faces and shaft clearance."),
                _step("Create the motor envelope", "Represent body limits, shaft axis, mounting face, mounting-hole locations, and connector or wire keep-out space.", "A motor envelope must prove mounting and collision fit without reproducing internal detail.", "The envelope captures every assembly-critical interface."),
                _step("Compare performance and accuracy", "Measure simplified critical features against the source and compare visible complexity or file behavior.", "Simplification is only successful if it improves usability without changing interfaces.", "Critical measurements match and irrelevant detail is visibly reduced."),
            ),
            ("All five lightweight references exist.", "Axes, mounting faces, holes, seats, shaft sizes, and envelopes remain accurate.", "Decorative geometry is not treated as essential."),
            ("Mistake: replacing a critical mounting face with a vague box. Recovery: restore the exact interface while simplifying the surrounding body.", "Mistake: deleting the verified source. Recovery: preserve a read-only source reference and derive a separate lightweight form.", "Mistake: keeping modeled threads and logos. Recovery: use nominal envelopes unless those details affect fit."),
            "Remove one additional feature from a copy, then argue whether the representation still supports every planned assembly check.",
            ("The verified source remains available.", "Wheel, bearing, shaft, spacer, and motor are simplified.", "Critical interfaces measure correctly.", "Collision envelopes remain useful.", "Decorative detail is omitted."),
            ("simplified representation", "collision envelope", "mounting face", "bearing seat", "keep-out", "model complexity"),
            (_check("Which wheel details must remain accurate?", "Overall diameter, width, axis, bore or hub interface, and collision envelope."), _check("When is simplification too aggressive?", "When it changes or removes geometry needed for fit, alignment, mounting, motion, or collision checks.")),
            (_media("images/academy/detailed-vs-simplified.svg", "A detailed wheel with decorative tread beside a lightweight wheel preserving diameter, width, bore, and axis.", "Simplification removes decorative detail while preserving assembly-critical geometry."), _media("images/academy/critical-interfaces.svg", "Wheel-module reference parts labeled with axes, mounting faces, holes, bearing seats, shaft diameters, and collision envelopes.", "Critical interfaces must remain accurate even in lightweight geometry.")),
        ),
        _lesson(
            "custom-interface-part", "Model a custom interface part",
            "Build one configurable part that connects verified hardware without disguising learner-selected clearances as facts.", 20,
            "Model a parametric custom interface with verified hardware controls, explicit design clearances, manufacturable material, and consistent axes.",
            "A bearing block, spacer carrier, or mounting plate turns purchased FTC hardware into a serviceable mechanism.",
            (parameters.title(), "Expressions", "Hardware inputs", "Design clearances", "Wall and edge material", "Manufacturing intent"),
            ("Choose a bearing block, spacer carrier, or mounting plate appropriate to the selected kit.", "Verify the hardware dimensions used by the interface."),
            (
                _step("Separate factual and chosen values", "Create a table with verified hardware dimensions on one side and selected clearance, tolerance, wall, and edge values on the other.", "Hardware size is evidence; fit and manufacturability choices depend on material and process.", "No design clearance is presented as a manufacturer fact."),
                _step(f"Create named {parameters}", ("Create variables for bearingOutsideDiameter, shaftDiameter, interfaceClearance, wallThickness, edgeMaterial, and partThickness." if onshape else "Create user parameters for bearingOutsideDiameter, shaftDiameter, interfaceClearance, wallThickness, edgeMaterial, and partThickness."), "Names make provenance and revision impact visible.", f"Each {parameter} has units, category, and source or rationale."),
                _step("Anchor the interface axis", f"Start the custom {body_term} around the same origin and shaft-axis convention used by the COTS references.", "A shared datum prevents later alignment from depending on arbitrary faces.", "The custom interface axis is concentric with the simplified bearing and shaft axes."),
                _step("Build the critical seat or bore", f"Use expressions combining verified size and chosen clearance to create the bearing seat, shaft clearance, or carrier interface.", "An expression makes the design decision explicit and editable.", "The feature measures to the documented input plus the stated design allowance."),
                _step("Add the mounting pattern", "Create a centered, clearly dimensioned pattern tied to reference axes and selected fasteners.", "Mounting holes must preserve alignment and adequate material when the hardware changes.", "The pattern is symmetric or otherwise intentionally related and fully constrained."),
                _step("Protect manufacturable material", "Set wall, edge, and part thickness from documented team requirements and the planned process.", "A mathematically valid cut can still leave fragile or unmanufacturable material.", "Measured minimum material meets the team's explicit design choices."),
                _step("Test the interface", f"Change one hardware {parameter} and one clearance {parameter} separately, then inspect regeneration and fit.", "Separate tests prove that factual inputs and design choices have distinct effects.", "The part updates predictably without shifting its reference axis."),
            ),
            ("Verified dimensions and design choices are visibly separated.", "All critical geometry uses named controls and expressions.", "Axes align and minimum material passes the team requirement."),
            ("Mistake: calling a chosen clearance verified. Recovery: label it as a design choice with process rationale.", "Mistake: dimensioning from an arbitrary imported edge. Recovery: reference the shared origin and functional axis.", "Mistake: adding holes before wall requirements. Recovery: set material rules and measure the narrowest remaining region."),
            "Create a second clearance value for a different manufacturing process and predict which geometry changes without editing the hardware inputs.",
            ("Hardware inputs are traceable.", "Clearances are labeled design choices.", "Named controls drive the part.", "The mounting pattern is clear.", "Wall and edge material are checked.", "The axis convention is preserved."),
            ("fit", "clearance", "tolerance", "wall thickness", "edge material", "parametric interface"),
            (_check("Is bearing clearance a manufacturer dimension?", "No. Bearing size may be verified, but clearance or interference is a design choice tied to material and process."), _check("What should remain fixed when a hardware diameter changes?", "The intended origin, functional axis, mounting relationships, and design intent should remain stable.")),
            (_media("images/academy/verified-vs-clearance.svg", "Verified bearing and shaft dimensions feed a custom interface alongside separately labeled design clearance and wall choices.", "Keep factual hardware inputs distinct from learner-selected fit and material decisions."),),
        ),
        _lesson(
            "organize-reusable-kit", "Organize a reusable FTC part kit",
            "Turn the working geometry into a traceable, version-aware kit another teammate can reuse safely.", 18,
            "Organize the kit with clear names, source notes, verification status, controlled references, and assembly-ready origins.",
            "FTC teams iterate quickly; uncontrolled copies and ambiguous revisions make fixes difficult to propagate.",
            ("Naming", "Source notes", "Version-aware references", "Verified and provisional status", "Reuse"),
            ("Complete the simplified references and custom interface.", "Resolve the naming and origin convention from lesson 1."),
            ((
                _step("Rename parts and features", "Use function, manufacturer or part number where relevant, and verification state in Part and feature names.", "Readable names make the Document auditable without opening every tab.", "No reusable Part or critical feature retains an ambiguous default name."),
                _step("Complete source notes", "Update the notes tab with provenance, critical dimensions, discrepancies, and physical-check status.", "Geometry and evidence must travel together.", "Every COTS Part points to a complete source record."),
                _step("Use tabs deliberately", "Keep source imports, simplified references, custom Part Studios, and the future Assembly in clearly scoped tabs.", "Tab structure prevents unrelated geometry from accumulating in one context.", "A teammate can find each responsibility from the tab bar."),
                _step("Control derived or linked content", "Use derived or linked content where it preserves a single controlled source; record the source Document, version, and update policy.", "Uncontrolled copies drift, while unreviewed live updates can also break downstream work.", "Each external reference has an owner and version-aware update decision."),
                _step("Mark verification state", "Add VERIFIED, MEASURE, or PROVISIONAL to notes or names without overstating certainty.", "Status makes unfinished evidence visible before assembly or fabrication.", "Every reference has one current, understandable status."),
                _step("Prepare assembly references", "Expose consistent axes, mounting faces, or mate-appropriate references without defining the full assembly.", "Preparation reduces later work while keeping this course focused on reusable parts.", "Each kit item has an obvious assembly interface."),
            ) if onshape else (
                _step("Rename components and features", "Use function, manufacturer or part number where relevant, and verification state in Component, Body, and feature names.", "Readable names make the Design auditable in the Browser and timeline.", "No reusable Component or critical feature retains an ambiguous default name."),
                _step("Complete source notes", "Maintain provenance, critical dimensions, discrepancies, and physical-check status with the Project or Design.", "Geometry and evidence must travel together.", "Every COTS Component points to a complete source record."),
                _step("Use projects and designs deliberately", "Separate controlled source Designs from the wheel-module kit while keeping them in an understandable Project structure.", "Project organization prevents unrelated geometry and duplicate files from accumulating.", "A teammate can locate source and kit Designs without guesswork."),
                _step("Control linked designs", "Use linked Designs where they preserve one controlled source; record ownership, version, and update policy instead of breaking links or copying Bodies casually.", "Uncontrolled copies drift, while unreviewed link updates can break downstream work.", "Each link has a version-aware update decision."),
                _step("Mark verification state", "Add VERIFIED, MEASURE, or PROVISIONAL to notes or names without overstating certainty.", "Status makes unfinished evidence visible before assembly or fabrication.", "Every reference has one current, understandable status."),
                _step("Prepare assembly references", "Expose consistent Component origins, axes, and mounting faces without defining the full assembly.", "Preparation reduces later joint work while keeping this course focused on reusable Components.", "Each kit item has an obvious assembly interface."),
            )),
            ("Names communicate function and identity.", "Source and revision notes accompany geometry.", "No uncontrolled duplicate is treated as authoritative.", "Verified and provisional states are visible."),
            ("Mistake: copying a COTS model into several files. Recovery: identify one controlled source and replace copies with version-aware references.", "Mistake: allowing linked content to update without review. Recovery: record a version and inspect changes deliberately.", "Mistake: embedding verification status only in memory. Recovery: place status in persistent names or notes."),
            "Ask a teammate to locate one source, its simplified geometry, and its verification status using only the kit organization; repair any ambiguity.",
            ("Parts, Components, Bodies, and features are clearly named.", "Source records are complete.", "References have version-aware ownership.", "Duplicates are controlled.", "Verification state is visible.", "Assembly interfaces are prepared."),
            ("derived content", "linked design", "version reference", "source of truth", "provisional geometry", "update policy"),
            (_check("Why not always use the newest linked version automatically?", "A new source version may change interfaces; updates need deliberate review."), _check("What makes a copy uncontrolled?", "It has no recorded source, owner, version, or process for receiving verified changes.")),
            (_media("images/academy/bodies-vs-components.svg", "Loose anonymous solids contrasted with named and status-labeled reusable parts or components.", "Names, ownership, and verification state turn geometry into a reusable kit."),),
        ),
        _lesson(
            "audit-revise-assembly", "Audit, revise, and prepare for assembly",
            "Audit the entire kit, perform a verified component substitution, and record what later assembly work must prove.", 18,
            "Deliver an audited wheel-module kit and substitute one verified COTS option without losing custom-interface design intent.",
            "An FTC assembly is only as trustworthy as the units, interfaces, sources, origins, and assumptions of its reusable parts.",
            ("Audit", "Substitution", "Assumptions", "Design invariants", "Assembly readiness"),
            ("Complete the organized kit.", "Obtain documentation or measurements for a different major wheel, bearing, motor, shaft, or spacer option."),
            (
                _step("Audit metadata", "Check units, names, source records, revisions, confidence, verification states, and missing assumptions for every item.", "Metadata failures can be as damaging as geometric errors.", "Every reference has complete traceable evidence or an explicit unresolved action."),
                _step("Audit geometry", "Check origins, axes, mounting faces, holes, seats, diameters, collision envelopes, and model complexity.", "Later assembly constraints depend on consistent and accurate interfaces.", "The kit follows one datum convention and contains no unexplained critical geometry."),
                _step("Select the replacement", "Record the second item's manufacturer, part number, source, revision or date, units, critical dimensions, confidence, and physical-check needs.", "The substitution must be evidence-based, not a visual swap.", "The replacement meets the same provenance standard as the original."),
                _step("Update named controls", f"Change only the verified hardware {parameters} affected by the replacement; do not silently alter design-clearance controls.", "Separating input categories reveals whether the custom design truly adapts.", "Changed parameters match documented dimensional differences."),
                _step("Inspect stable geometry", "Confirm the kit origin, functional axis, mounting intent, and unaffected references remain stable.", "A replacement should not disturb geometry unrelated to its interface.", "The same datums and intended relationships survive regeneration."),
                _step("Evaluate the custom interface", "Measure fit, wall and edge material, mounting relationships, and collision envelopes after the substitution.", "Successful regeneration does not prove the new hardware is supported or serviceable.", "The interface passes or has specific, documented redesign needs."),
                _step("Prepare the assembly handoff", "List the joints or mates, motion, interference, stack-up, retention, and service checks required in Assemblies and Motion.", "Part readiness and assembly proof are different responsibilities.", "The handoff names concrete checks without pretending they are already complete."),
            ),
            ("Units, names, origins, axes, interfaces, dimensions, sources, complexity, and assumptions are audited.", "The replacement source and parameter changes are documented.", "Stable geometry and assembly follow-up checks are explicit."),
            ("Mistake: changing clearance to make a replacement appear compatible. Recovery: evaluate hardware inputs first and document any design-choice revision separately.", "Mistake: checking only the custom part. Recovery: inspect the whole wheel, bearing, shaft, spacer, and motor stack.", "Mistake: declaring assembly-ready without motion review. Recovery: list required constraints, interference, and service checks for the next course."),
            CHALLENGE,
            ("The metadata audit is complete.", "The geometry audit is complete.", "The replacement has verified provenance.", "Changed parameters match source differences.", "Stable datums are confirmed.", "The custom interface is evaluated.", "Assembly and Motion checks are listed."),
            ("design invariant", "substitution", "stack-up", "retention", "assembly handoff", "audit trail"),
            (_check("What must remain separate during substitution?", "Verified hardware changes and learner-selected clearance or tolerance changes must be recorded separately."), _check("What remains for Assemblies and Motion?", "Placement relationships, intended motion, interference, stack-up, retention, and service access must still be proven.")),
            (_media("images/academy/origin-axis-consistency.svg", "Multiple wheel-module references retain one common axis and consistent mounting-face origins after substitution.", "Stable origins and axes are key design invariants during hardware replacement."), _media("images/academy/verified-vs-clearance.svg", "Verified replacement dimensions and separate design-clearance values feeding the custom interface.", "Audit hardware changes separately from design-choice changes.")),
        ),
    )


def build_course(platform, pathway_name):
    lessons = lessons_for(platform)
    return {
        "slug": COURSE_SLUG, "platform": platform,
        "title": "Parts or Components and FTC Libraries",
        "summary": "Build a reusable FTC wheel-module kit from verified COTS references and one custom parametric interface.",
        "level": "FTC-Ready CAD", "difficulty": "Intermediate",
        "duration_minutes": sum(lesson["estimated_minutes"] for lesson in lessons),
        "status": "Live",
        "outcome": "A reusable FTC wheel-module part kit containing verified COTS reference geometry, lightweight assembly references, complete provenance records, and one custom parametric interface part.",
        "prerequisites": ("Quick Start and CAD Mental Model", "Sketching and Parameters/Variables"),
        "skills": ("Part structure", "COTS verification", "Reference simplification", "Parametric interfaces", "Version-aware reuse"),
        "tools": (pathway_name, "Manufacturer documentation, approved library data, or physical measurement", "STEP or another appropriate interchange file"),
        "lessons": lessons,
        "brief": "Create a traceable, lightweight wheel-module kit that separates purchased hardware facts from custom interface decisions and is ready for later assembly work.",
        "objectives": ("Plan reusable part ownership and datums.", "Verify and inspect COTS source geometry.", "Preserve accurate interfaces in lightweight representations.", "Build a custom parametric interface from verified inputs and explicit design choices.", "Organize, audit, and revise a version-aware FTC part kit."),
        "constraints": ("Do not assume universal FTC hardware dimensions.", "Use manufacturer documentation, an approved CAD library, or physical measurement for hardware inputs.", "Keep provenance and verification state with every COTS reference.", "Preserve functional interfaces while removing irrelevant detail."),
        "checkpoints": tuple(checkpoint for lesson in lessons for checkpoint in lesson["checkpoints"][:1]),
        "challenge": CHALLENGE, "artifacts": ARTIFACTS, "rubric": RUBRIC,
        "reference_specifications": REFERENCE_SPECIFICATIONS,
        "related": ("sketching-and-parameters", "assemblies-and-motion"),
        "equivalent_slug": COURSE_SLUG,
    }
