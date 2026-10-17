"""Assemblies and Motion foundation course content."""

COURSE_SLUG = "assemblies-and-motion"

CHALLENGE = (
    "Modify the wheel module for a wider verified wheel while preserving its outer packaging "
    "envelope. Update the relevant component or reference, adjust spacer or plate-spacing "
    "decisions, preserve the rotational architecture, recheck interference and retention, "
    "demonstrate a service path, explain which assembly relationships remained stable, and "
    "identify compromises created by the wider wheel."
)

ARTIFACTS = (
    "A reusable wheel-module assembly with structural support, bearing, shaft or axle, wheel, spacers, retention, and optional motor envelope.",
    "A motion plan identifying fixed structure, rotating members, functional axes, and intended degrees of freedom.",
    "Evidence of correct fixed and rotating relationships and an intentional assembly origin.",
    "Section, interference, clearance, and service-access evidence for the verified hardware stack.",
    "A wider-wheel revision record naming stable relationships, changed spacing decisions, and resulting compromises.",
)

RUBRIC = (
    {"criterion": "Assembly architecture", "evidence": "The hierarchy, origin, fixed structure, rotating members, and live- or dead-axle behavior match the motion plan."},
    {"criterion": "Relationships and stack", "evidence": "Fixed and rotational relationships, spacers, retention, and hardware envelopes create a plausible supported stack."},
    {"criterion": "Verification", "evidence": "Motion, interference, clearances, tool access, and replacement paths are checked with observable evidence."},
    {"criterion": "Diagnosis and revision", "evidence": "A broken relationship is repaired systematically and the wider-wheel change preserves intended behavior within the envelope."},
)

REFERENCE_SPECIFICATIONS = (
    "Selected live-axle or dead-axle architecture", "Wheel diameter and width",
    "Bearing outside diameter, bore, and width", "Shaft or axle diameter and usable length",
    "Spacer, washer, and retention dimensions", "Structural plate or bracket interfaces",
    "Optional motor and gearbox envelope", "Maximum wheel-module packaging envelope",
    "Team minimum moving and static clearance", "Required tool and component-removal paths",
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
    relation = "mate" if onshape else "joint"
    relations = "mates" if onshape else "joints"
    axis_reference = "mate connector" if onshape else "joint origin"
    fixed_relation = "Fastened mate" if onshape else "rigid joint"
    rotating_relation = "Revolute mate" if onshape else "revolute joint"

    return (
        _lesson(
            "plan-degrees-of-freedom", "Plan the assembly and its degrees of freedom",
            "Describe the physical wheel module as fixed structure, rotating members, and intentional freedoms before constraining it.", 18,
            "Create a motion plan naming the assembly origin, hierarchy, fixed components, rotating components, functional axes, and intended degrees of freedom.",
            "An FTC mechanism that is constrained before its motion is understood often becomes locked, unstable, or physically unrealistic.",
            ("Assembly representation", "Degrees of freedom", "Fixed and moving components", "Assembly origin", "Functional axes", "Parent and child relationships"),
            ("Open the verified wheel-module part kit from the preceding course.", "Confirm selected hardware and decide whether the architecture is live axle or dead axle."),
            (
                _step("Describe the physical behavior", "Write one sentence each for what the structure supports, what rotates, and what must remain removable.", "Constraints should represent physical behavior rather than merely stop screen movement.", "The plan distinguishes support, motion, and service responsibilities."),
                _step("Choose live or dead axle", "Select live axle if shaft and wheel rotate together, or dead axle if the wheel rotates around a fixed axle; cite the selected hardware interfaces.", "The architecture determines which bearing race and member must rotate.", "The plan names one architecture and identifies the rotating member."),
                _step("Count intended freedoms", "For every item, list translation and rotation that should remain after assembly relationships are applied.", "Degrees-of-freedom accounting predicts whether the final model should move or stay fixed.", "Only the intended wheel-axis rotation remains in the finished-state plan."),
                _step("Select the assembly origin", "Place the intended origin on a stable structural datum with a functional wheel or shaft axis passing through it.", "A deliberate origin makes packaging, mirroring, and replacement comparisons repeatable.", "The origin and primary axis can be explained without referencing a temporary edge."),
                _step("Sketch the hierarchy", "Draw the base structure as parent, reusable hardware or a wheel subassembly as children, and repeated instances where needed.", "Hierarchy controls reuse and reduces accidental duplication.", "Each item has one owner and a clear parent context."),
                _step("Sequence the relationships", f"Plan fixed relationships first, rotational {relations} second, and axial positioning or limits last.", "A deliberate sequence makes constraint failures easier to isolate.", "The motion plan lists relationship order and expected motion after each stage."),
            ),
            ("The motion plan identifies fixed and rotating members.", "Live- or dead-axle behavior is explicit.", "The final intended degree of freedom and assembly origin are documented."),
            ("Mistake: adding constraints until parts stop drifting. Recovery: remove them and write the intended physical behavior first.", "Mistake: calling any spinning wheel live axle. Recovery: identify whether the shaft rotates with the wheel.", "Mistake: choosing an origin on decorative geometry. Recovery: use a structural datum and functional axis."),
            "Reverse the proposed axle architecture conceptually and list which members and bearing race would change behavior.",
            ("I described the physical assembly.", "I selected and justified live or dead axle.", "I counted intended freedoms.", "The origin and axis are stable.", "The hierarchy is clear.", "Relationship order is planned."),
            ("assembly", "degree of freedom", "live axle", "dead axle", "functional axis", "parent", "child"),
            (_check("Why plan motion before adding relationships?", "The plan defines which freedom must remain, preventing constraints from locking or misrepresenting the mechanism."), _check("What rotates in a typical dead-axle arrangement?", "The wheel and its rotating bearing member rotate around a shaft or axle fixed to structure.")),
            (_media("images/academy/assembly-degrees-of-freedom.svg", "A wheel module with fixed structure and arrows showing the single intended rotation after translations are removed.", "A finished wheel module normally retains only its intended rotation."), _media("images/academy/assembly-hierarchy.svg", "A tree showing a wheel-module assembly, fixed structure, reusable wheel subassembly, motor reference, and repeated hardware instances.", "Hierarchy separates ownership, reuse, and placement.")),
        ),
        _lesson(
            "insert-organize-components", "Insert and organize components",
            "Build an intentional assembly hierarchy from the verified kit without creating uncontrolled copies.", 18,
            "Insert, name, ground, and organize every wheel-module item as a controlled instance or occurrence with consistent origins.",
            "Clear ownership and hierarchy let FTC teams replace hardware and diagnose motion without guessing which copy is authoritative.",
            (("Assemblies", "Instances", "Mate connectors", "Fixed base", "Subassemblies", "Intentional reuse") if onshape else
             ("Components", "Occurrences", "Joint origins", "Grounded base", "Subassemblies", "Intentional reuse")),
            ("Complete the motion plan.", "Confirm every inserted item comes from the verified wheel-module kit."),
            ((
                _step("Create the Assembly", "Create and name a wheel-module Assembly tab, then display its origin and principal axes.", "The Assembly is the placement and motion context, separate from Part definition.", "A named empty Assembly has a visible datum convention."),
                _step("Insert controlled instances", "Insert the structural plate or bracket, bearing, shaft, wheel, spacers, retention hardware, and optional motor reference as Instances.", "Instances intentionally reuse verified Parts without creating unrelated copies.", "Every required physical item appears as an identifiable Instance."),
                _step("Fix the intended base", "Fix only the structural base Instance that owns the assembly origin.", "One grounded reference removes global drift without hiding incorrect relationships elsewhere.", "The base cannot move, while unconstrained hardware still can."),
                _step("Inspect mate connectors", "Show or create Mate connectors on functional faces and axes using the origin convention from the part kit.", "Explicit connectors make orientation and later replacement predictable.", "Every key Instance has an axis-aligned connector at its real interface."),
                _step("Name instances and repeats", "Use functional names with side or sequence identifiers for duplicate spacers, washers, or bearings.", "Repeated Instances are intentional reuse only when each placement remains understandable.", "No duplicate has an ambiguous generated name."),
                _step("Use a subassembly deliberately", "Group a reusable wheel-and-hub set only if it has meaningful internal relationships and will be reused.", "A subassembly should communicate repeated function, not hide disorganization.", "Hierarchy remains shallow and every subassembly has a stated purpose."),
            ) if onshape else (
                _step("Create the assembly design", "Open the wheel-module Design, display its origin, and confirm every reusable item is a Component.", "Assembly behavior belongs to Components and their Occurrences, not loose Bodies.", "The Browser shows a named component hierarchy and stable datum."),
                _step("Insert controlled occurrences", "Insert or activate Occurrences for the plate or bracket, bearing, shaft, wheel, spacers, retention, and optional motor reference.", "Occurrences intentionally place reusable Components without creating unrelated copies.", "Every required physical item appears as an identifiable Occurrence."),
                _step("Ground the intended base", "Ground only the structural base Occurrence that owns the assembly origin.", "One grounded reference removes global drift without hiding incorrect relationships elsewhere.", "The base cannot move, while unconstrained hardware still can."),
                _step("Inspect joint origins", "Show or create Joint origins on functional faces and axes using the origin convention from the part kit.", "Explicit origins make orientation and later replacement predictable.", "Every key Component has an axis-aligned origin at its real interface."),
                _step("Name occurrences and repeats", "Use functional names with side or sequence identifiers for duplicate spacers, washers, or bearings.", "Repeated Occurrences are intentional reuse only when each placement remains understandable.", "No duplicate has an ambiguous generated name."),
                _step("Use a subassembly deliberately", "Group a reusable wheel-and-hub set only if it has meaningful internal relationships and will be reused.", "A subassembly should communicate repeated function, not hide disorganization.", "Hierarchy remains shallow and every subassembly has a stated purpose."),
            )),
            ("One intentional base is fixed or grounded.", "Every required item is a named Instance or Occurrence.", "Functional connectors or origins use consistent axes.", "Duplicate hardware is deliberate and traceable."),
            ("Mistake: fixing every item in place. Recovery: leave only the intended base grounded and define physical relationships.", "Mistake: duplicating loose geometry. Recovery: insert another controlled Instance or Occurrence from the source item.", "Mistake: nesting everything in subassemblies. Recovery: use hierarchy only for independently reusable behavior."),
            "Insert a second wheel occurrence or instance, name it clearly, and explain whether it belongs in this module or a higher-level drivetrain assembly.",
            ("The assembly context is named.", "Required items are inserted from verified sources.", "Only the base is grounded.", "Names distinguish repeats.", "Axes are consistent.", "Any subassembly has a purpose."),
            ("instance", "occurrence", "ground", "fix", "subassembly", "controlled reuse", "assembly hierarchy"),
            (_check("What is the difference between reuse and an uncontrolled copy?", "Reuse places another traceable instance or occurrence of a controlled source; an uncontrolled copy loses source and revision ownership."), _check("Why ground only the intended base?", "Other components must be positioned by physical relationships so missing or incorrect constraints remain visible.")),
            (_media("images/academy/assembly-hierarchy.svg", "A simple hierarchy separating fixed structure, moving wheel hardware, retention, and an optional motor reference.", "A shallow, purposeful hierarchy keeps repeated hardware traceable."), _media("images/academy/origin-joint-alignment.svg", "Several assembly references with connector origins centered on the same functional axis and arrows showing consistent orientation.", "Connector or joint-origin axes must agree before relationships are added.")),
        ),
        _lesson(
            "constrain-fixed-structure", "Constrain fixed structure",
            "Attach supports and fixed hardware without consuming the wheel module's intended rotation.", 19,
            "Constrain the plate, bearing support, and fixed hardware with correctly oriented fixed relationships while leaving rotating members free.",
            "Incorrectly fixing a bearing, shaft, or hub can make an FTC assembly look complete while representing impossible physics.",
            (("Fastened mates", "Mate-connector orientation", "Offsets", "Connector reorientation") if onshape else
             ("Rigid joints", "Rigid groups", "Joint-origin orientation", "Offsets")),
            ("Insert and name the complete unconstrained kit.", "Keep the motion plan visible during each relationship decision."),
            (
                _step("Identify fixed interfaces", "Mark the structure, bearing outer-race support, fixed fasteners, and any motor reference that should not move relative to the base.", "Fixed relationships must follow real clamping and support paths.", "Every planned fixed item has a physical reason for being fixed."),
                _step("Orient the first fixed interface", f"Align the relevant {axis_reference} axes and face normals before applying a {fixed_relation}.", "Correct orientation prevents flipped parts and unexplained offset signs.", "The bearing support sits on its intended face with its axis aligned."),
                _step("Apply structural relationships", f"Use {fixed_relation}s for the plate, bearing support, and genuinely fixed hardware.", "Fixed structure should move as one supported system without capturing rotating members.", "Dragging fixed hardware produces no relative movement."),
                _step("Use offsets intentionally", "Apply documented axial offsets only for real thickness, shoulder, recess, or spacer locations.", "Offsets should represent physical stack dimensions rather than repair poor connector placement.", "Every nonzero offset maps to a measured or chosen stack value."),
                _step("Reorient a connector when needed", f"Reverse or rotate the {axis_reference} orientation instead of entering a misleading negative offset.", "Orientation is a directional relationship; correcting it makes later edits readable.", "Axes and face normals point consistently and offsets have intuitive signs."),
                _step("Test remaining freedom", "Drag or manipulate the assembly and confirm the base structure is fixed while wheel and shaft members retain their planned freedom.", "Testing now isolates fixed-structure errors before rotation is added.", "Fixed items stay together and intended rotating members are not accidentally locked."),
            ),
            ("The plate and bearing support are fixed to the base.", "Outer-race support follows the architecture.", "Offsets have physical meanings.", "Rotating members remain free at this stage."),
            (f"Mistake: using a {fixed_relation} on the wheel because it looks aligned. Recovery: remove it and reserve a rotational relationship for the functional axis.", "Mistake: compensating for a reversed axis with arbitrary offsets. Recovery: reorient the connector or origin first.", "Mistake: rigidly grouping unrelated hardware. Recovery: group only items that are physically locked together."),
            "Temporarily reverse one fixed-interface orientation, observe the result, then repair it without changing physical stack dimensions.",
            ("Fixed interfaces are identified.", "Connector or origin orientation is correct.", "Fixed relationships follow physical support.", "Offsets are traceable.", "Rotating members remain unlocked."),
            (("fixed relationship", "Fastened mate", "mate connector", "offset", "face normal", "outer race") if onshape else
             ("fixed relationship", "rigid joint", "rigid group", "joint origin", "offset", "face normal", "outer race")),
            (_check("Should a fixed relationship be used merely to stop visual movement?", "No. It should represent a real physical connection that removes all relative motion."), _check("What should be checked before changing an offset sign?", "Check whether the connector or joint-origin axis and face normal are reversed.")),
            (_media("images/academy/fixed-vs-revolute.svg", "A fixed relationship removes all relative motion while a revolute relationship preserves rotation around one aligned axis.", "Fixed and revolute relationships remove different degrees of freedom."), _media("images/academy/origin-joint-alignment.svg", "Two interface origins share a center and axis, while a misaligned example shows offset and reversed direction.", "Align centers, axes, and orientation before constraining interfaces.")),
        ),
        _lesson(
            "create-rotational-motion", "Create rotational motion",
            "Represent live-axle or dead-axle behavior with one intentional rotational freedom.", 21,
            "Create and verify rotational relationships so wheel, shaft, and bearing members move according to the selected axle architecture.",
            "Correct rotational architecture affects power transfer, bearing behavior, retention, and failure modes in FTC drivetrains.",
            (("Revolute mates", "Mate axes", "Mate limits", "Live axle", "Dead axle") if onshape else
             ("Revolute joints", "Joint axes", "Joint limits", "Live axle", "Dead axle")),
            ("Complete fixed-structure relationships.", "Confirm which bearing race follows structure and which follows the rotating member."),
            (
                _step("Trace the rotation path", "Follow torque and motion from wheel to hub, shaft or axle, bearing inner race, bearing outer race, and structure.", "A functional relationship must match the selected hardware stack, not a generic animation.", "The path identifies exactly which members rotate together."),
                _step("Align the rotational axis", f"Place the wheel and shaft references concentrically and align the relevant {axis_reference} or axis definition.", "A revolute relationship requires one geometrically consistent axis.", "Wheel, bearing, and shaft centers are collinear in section view."),
                _step("Build the dead-axle case", f"For a dead axle, keep the axle fixed to structure and apply a {rotating_relation} so the wheel or bearing inner member rotates around it.", "Dead-axle behavior separates fixed support from the rotating wheel system.", "The axle stays still while the wheel rotates freely."),
                _step("Build the live-axle case", f"For a live axle, lock wheel or hub to shaft as one rotating set and apply the {rotating_relation} between that set and the supported bearing axis.", "Live-axle behavior transmits rotation through the shaft.", "Wheel and shaft rotate together while the bearing outer race remains fixed."),
                _step("Apply limits only when physical", "Add rotational limits only when a real stop, cable, or mechanism requirement restricts travel; omit them for unrestricted wheel rotation.", "Artificial limits can disguise collisions or misunderstand continuous motion.", "The motion range matches the physical design rather than a demonstration preference."),
                _step("Verify races and freedom", "Drag or drive rotation and observe wheel, shaft, bearing inner race, outer race, and structure independently.", "Bearing behavior is the clearest test that the architecture is represented correctly.", "Exactly the intended members rotate and no translation remains."),
            ),
            ("Wheel, shaft, and bearing behavior matches the chosen architecture.", "Axes remain aligned through motion.", "Only intentional rotation remains.", "Limits, if present, correspond to physical restrictions."),
            ("Mistake: fixing shaft and wheel together in a dead-axle design. Recovery: keep the axle fixed and rotate the wheel system around it.", "Mistake: allowing the bearing outer race to spin in its structural seat. Recovery: fix the outer-race reference to support.", "Mistake: adding a revolute relationship on misaligned axes. Recovery: repair axis placement before motion."),
            "Model the opposite axle architecture in a duplicate assembly and compare which members need fixed versus rotating relationships.",
            ("The torque and motion path is documented.", "Axes are concentric.", "Live- or dead-axle behavior is correct.", "Bearing races behave plausibly.", "No unintended translation remains.", "Limits reflect physical needs."),
            ("revolute relationship", "live axle", "dead axle", "inner race", "outer race", "joint axis", "mate axis", "motion limit"),
            (_check("What rotates together in a live-axle design?", "The wheel or hub and shaft rotate as one set, supported by the bearing inner race."), _check("What remains fixed in a dead-axle design?", "The axle remains fixed to structure while the wheel system rotates around it.")),
            (_media("images/academy/live-vs-dead-axle.svg", "Side-by-side live-axle and dead-axle sections with arrows showing whether the shaft rotates with the wheel or remains fixed.", "The selected axle architecture determines which members rotate together."), _media("images/academy/fixed-vs-revolute.svg", "Fixed structure beside a wheel retaining one rotational degree of freedom about its axis.", "A revolute relationship preserves intentional rotation instead of locking the wheel.")),
        ),
        _lesson(
            "spacers-retention-motor", "Add spacers, retention, and motor references",
            "Turn the aligned wheel and shaft into a plausible supported axial stack with serviceable retention.", 19,
            "Position spacers, washers, retention hardware, and an optional motor envelope into a supported, nonzero-clearance assembly stack.",
            "FTC wheel modules must survive axial loads, remain serviceable, and leave room for real hardware and tools.",
            ("Axial stack-up", "Spacers", "Washers", "Retention", "Motor envelopes", "Fastener access"),
            ("Verify rotational behavior first.", "Use dimensions from the selected spacer and retention hardware rather than generic values."),
            (
                _step("Draw the axial stack", "List structural face, bearing races, spacers, wheel or hub, washers, retention hardware, and end clearance in order.", "A stack diagram exposes missing support and impossible overlaps before more relationships are added.", "Every axial face has a neighboring item or intentional clearance."),
                _step("Insert and position spacers", f"Insert controlled spacer instances or occurrences and position them concentrically with axial offsets from real lengths.", "Spacers carry axial positioning decisions and prevent floating components.", "Wheel location is controlled by physical spacer faces, not visual alignment."),
                _step("Add washers and retention", "Represent washers, shaft collars, clips, nuts, bolts, or other selected retention with documented envelopes and engagement.", "Retention prevents axial escape and must match the real shaft architecture.", "The rotating stack has a plausible retained end condition."),
                _step("Preserve operating clearance", "Add the team's chosen axial or radial allowance instead of mating moving faces at unrealistic zero clearance.", "Real parts need clearance for tolerance, deflection, and free rotation.", "Moving members have measurable nonzero clearance with its rationale recorded."),
                _step("Add motor and gearbox envelope", "Place a simplified verified motor or gearbox reference on its mounting axis and include connector or cable keep-out space.", "Power hardware can collide with the wheel stack even when mounting holes align.", "The envelope is oriented and located from real interfaces."),
                _step("Check support and access", "Trace every component to structural support and confirm a tool can reach each retention fastener.", "Unsupported floating items and inaccessible hardware make the assembly physically implausible.", "No item floats and retention can be installed and removed."),
            ),
            ("The axial stack has no unexplained gaps or overlaps.", "Retention prevents axial escape.", "Moving interfaces have deliberate clearance.", "Motor and tool envelopes are represented."),
            ("Mistake: aligning spacers without constraining their faces. Recovery: position them from real axial interfaces and lengths.", "Mistake: mating moving faces with zero clearance. Recovery: add a documented design allowance.", "Mistake: modeling a shaft collar without tool access. Recovery: reserve an installation and adjustment path."),
            "Replace one spacer with a different verified length and predict how wheel position, retention, and envelope clearance change.",
            ("The stack order is documented.", "Spacers control axial position.", "Retention is plausible.", "Clearance is nonzero and justified.", "The motor envelope is placed.", "Every item is supported and serviceable."),
            ("axial stack", "spacer", "washer", "shaft collar", "retention", "endplay", "zero-clearance stack"),
            (_check("Why is a visually aligned spacer not enough?", "Its concentric and axial relationships must be defined from physical faces and verified length."), _check("Why avoid zero clearance between moving faces?", "Manufacturing tolerance, deflection, and friction require a deliberate operating allowance.")),
            (_media("images/academy/wheel-stack-retention.svg", "A sectioned stack of structure, bearing, shaft, spacers, wheel, washer, and retention hardware with axial clearances labeled.", "A plausible assembly stack supports every item and includes retention and operating clearance."),),
        ),
        _lesson(
            "inspect-motion-service", "Inspect motion, interference, and service access",
            "Collect evidence that the module moves freely, stays supported, avoids collisions, and can be maintained.", 20,
            "Verify intended motion, structural stability, interference, minimum clearances, tool access, and wheel and bearing replacement paths.",
            "A wheel module that animates but cannot be assembled, cleared, or serviced is not ready for an FTC robot.",
            ("Motion testing", "Section views", "Interference", "Minimum clearance", "Tool access", "Removal paths"),
            ("Complete the supported stack and optional motor envelope.", "Record the team's minimum clearance and service-tool requirements."),
            (
                _step("Run a motion test", "Drag or drive the intended rotation through a useful range while observing every member.", "Dynamic inspection reveals unintended motion that a static view conceals.", "The wheel rotates freely, fixed structure stays fixed, and no extra member drifts."),
                _step("Inspect section views", "Create sections through the functional axis and key mounting interfaces.", "Internal bearing seats, spacer contact, retention, and hidden gaps need direct inspection.", "The section shows a coherent supported stack without internal overlap."),
                _step("Run interference checks", "Inspect or calculate interference for the verified configuration and distinguish intended contact from collisions.", "Contact at clamped interfaces may be correct; overlap through moving hardware is not.", "Every reported interference is classified and resolved or justified."),
                _step("Measure minimum clearance", "Measure the tightest moving, static, motor-envelope, and cable-aware clearances against team requirements.", "A generic 'no collision' result does not quantify tolerance or deflection margin.", "The smallest relevant clearance is recorded with its location."),
                _step("Verify tool access", "Represent or reason through wrench, driver, hex key, collar, and fastener access along real approach directions.", "A fastener that exists but cannot be reached is not serviceable.", "Every service fastener has an unobstructed tool path."),
                _step("Test removal paths", "Simulate wheel and bearing removal without hiding unrelated structure; identify the order of retention and spacer removal.", "FTC repair time depends on a plausible sequence and adequate extraction space.", "Wheel and bearing each have a documented maintenance path."),
                _step("Capture evidence", "Record clear views or notes showing motion, fixed structure, sections, collisions, clearances, and service sequence.", "Review evidence lets another teammate evaluate claims without reproducing every interaction.", "The artifact demonstrates all four required claims: free motion, no unintended movement, no obvious collision, and plausible maintenance."),
            ),
            ("Intended motion is free and fixed items remain fixed.", "Interference findings are classified.", "Minimum clearance is measured.", "Wheel and bearing have plausible removal paths."),
            ("Mistake: treating successful drag as a complete review. Recovery: add section, interference, clearance, and service checks.", "Mistake: hiding parts to fake removal. Recovery: trace a real extraction path and removal order.", "Mistake: ignoring cables and motor connectors. Recovery: include keep-out envelopes in the clearance review."),
            "Reduce one service clearance deliberately, identify the first maintenance failure, then restore a defensible path.",
            ("Motion evidence is captured.", "Fixed structure does not move.", "Sections reveal the stack.", "Interference is resolved or explained.", "Clearance is quantified.", "Tools can reach retention.", "Wheel and bearing can be replaced."),
            ("interference", "clearance", "section view", "tool envelope", "removal path", "service sequence", "intended contact"),
            (_check("Does no detected interference prove adequate clearance?", "No. Minimum margin must still be measured against tolerance, deflection, and team requirements."), _check("What makes a maintenance path plausible?", "It identifies retention order, tool access, extraction direction, and space for the component to leave the assembly.")),
            (_media("images/academy/interference-vs-service.svg", "One wheel module shows a collision and blocked tool path while another shows measured clearance and an unobstructed removal arrow.", "Interference freedom and service access are related but separate checks."),),
        ),
        _lesson(
            "diagnose-repair-assembly", "Diagnose and repair a broken assembly",
            "Use degrees-of-freedom evidence and relationship order to repair failures without rebuilding the module.", 20,
            "Diagnose and repair a broken wheel-module assembly, then adapt it to changed hardware while preserving stable relationships.",
            "Fast FTC iteration depends on finding the failed relationship or assumption instead of recreating an assembly before every match.",
            ("Debugging workflow", "Grounding errors", "Axis misalignment", "Conflicting relationships", "Missing retention", "Hardware revision"),
            ("Duplicate the verified assembly as a debugging copy.", "Choose one verified hardware dimension that can be changed safely for diagnosis."),
            (
                _step("Classify the symptom", "Decide whether everything moves together, nothing moves, an axis is misaligned, a member floats, or motion appears connected only visually.", "Symptom categories narrow the likely relationship failure.", "The problem is described in terms of actual degrees of freedom."),
                _step("Check grounding and hierarchy", "Confirm only the intended base is fixed or grounded and that the moving item belongs to the expected parent or subassembly.", "An incorrectly grounded child can lock a whole mechanism; a loose parent can move everything.", "Global and local movement match the hierarchy plan."),
                _step("Inspect relationship order", f"Suppress or review recent {relations} one at a time, looking for duplicates, conflicts, and fixed relationships on rotating members.", "One-at-a-time isolation preserves working structure and identifies the first bad assumption.", "One specific relationship explains the lock, drift, or conflict."),
                _step("Check axes and orientation", f"Compare centers, directions, and face normals for each {axis_reference}; repair reversed or offset definitions.", "Components can look concentric from one view while their functional axes remain skewed.", "Section and axis views show true collinearity."),
                _step("Check retention and connection", "Trace physical support and torque transfer through bearings, shaft, hub, spacers, and retention hardware.", "Visual proximity is not a functional connection, and missing retention permits impossible axial motion.", "Every fixed, rotating, and retained relationship has a physical counterpart."),
                _step("Change one hardware dimension", "Update one verified wheel, bearing, spacer, or shaft dimension and regenerate without deleting the assembly.", "A controlled revision tests whether relationships use stable axes and faces.", "The change propagates and only affected stack decisions require repair."),
                _step("Complete the wider-wheel challenge", "Substitute the wider verified wheel, adjust spacing while holding the outer envelope, then repeat motion, interference, retention, and service checks.", "The challenge combines diagnosis with a real packaging tradeoff.", "The repaired assembly preserves rotation and documents stable relationships and compromises."),
            ),
            ("The failure is classified before editing.", "Grounding, hierarchy, relationship order, axes, and retention are checked systematically.", "A hardware change is repaired without a rebuild.", "The wider-wheel revision remains inside the envelope."),
            ("Mistake: deleting all relationships at once. Recovery: restore and isolate one relationship in build order.", "Mistake: grounding the troublesome component. Recovery: repair its physical relationships instead of hiding freedom.", "Mistake: changing several hardware values together. Recovery: return to the last valid state and test one verified input at a time."),
            CHALLENGE,
            ("I classified the symptom.", "Grounding and hierarchy are correct.", "Duplicate or conflicting relationships are removed.", "Axes and orientation are repaired.", "Retention and torque paths are plausible.", "One hardware change survives without rebuilding.", "The wider-wheel challenge is verified and explained."),
            ("overconstrained", "underconstrained", "conflicting relationship", "reversed orientation", "floating component", "functional connection", "debug sequence"),
            (_check("What should be inspected first when everything moves together?", "Check whether the intended base is grounded and whether the hierarchy has a stable parent."), _check("What should be inspected first when nothing moves?", "Look for extra grounding, fixed relationships on rotating members, rigid grouping, or duplicate constraints.")),
            (_media("images/academy/assembly-degrees-of-freedom.svg", "A fixed structure and wheel with the intended single rotational freedom highlighted for debugging.", "Compare observed movement with the planned degree of freedom."), _media("images/academy/interference-vs-service.svg", "A wider wheel comparison showing tightened clearance, adjusted spacing, retention, and a maintained removal path.", "After repair or substitution, repeat both motion and service checks.")),
        ),
    )


def build_course(platform, pathway_name):
    lessons = lessons_for(platform)
    return {
        "slug": COURSE_SLUG, "platform": platform,
        "title": "Assemblies and Motion",
        "summary": "Turn a verified FTC wheel-module part kit into a constrained, moving, inspectable, and serviceable assembly.",
        "level": "FTC-Ready CAD", "difficulty": "Intermediate",
        "duration_minutes": sum(lesson["estimated_minutes"] for lesson in lessons),
        "status": "Live",
        "outcome": "A reusable FTC wheel-module assembly with fixed structure, verified rotational behavior, plausible stack-up and retention, and documented clearance and service evidence.",
        "prerequisites": ("Quick Start and CAD Mental Model", "Sketching and Parameters/Variables", "Parts or Components and FTC Libraries"),
        "skills": ("Assembly planning", "Fixed and rotational relationships", "Live- and dead-axle motion", "Stack-up and retention", "Interference and service review", "Assembly diagnosis"),
        "tools": (pathway_name, "Completed verified wheel-module part kit", "Selected hardware specifications and team clearance requirements"),
        "lessons": lessons,
        "brief": "Assemble the verified wheel-module kit so its physical support, intended motion, retention, clearances, and maintenance path can be reviewed before robot integration.",
        "objectives": ("Plan hierarchy and degrees of freedom before constraining parts.", "Create correct fixed and rotating relationships for live- or dead-axle hardware.", "Build a plausible supported and retained axial stack.", "Verify motion, interference, clearance, and service access.", "Diagnose failures and adapt the module to a wider wheel."),
        "constraints": ("Use the verified hardware selected in the preceding course.", "Do not prescribe universal FTC hardware dimensions.", "Preserve only physically intended degrees of freedom.", "Keep the wider-wheel revision inside the original outer packaging envelope."),
        "checkpoints": tuple(checkpoint for lesson in lessons for checkpoint in lesson["checkpoints"][:1]),
        "challenge": CHALLENGE, "artifacts": ARTIFACTS, "rubric": RUBRIC,
        "reference_specifications": REFERENCE_SPECIFICATIONS,
        "related": ("parts-components-ftc-libraries", "parallel-plate-drivetrain"),
        "equivalent_slug": COURSE_SLUG,
    }
