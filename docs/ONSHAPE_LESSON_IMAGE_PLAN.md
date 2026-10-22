# Onshape Academy image plan

This is the capture brief for the two live Onshape courses. Step numbers match the lesson pages. **Essential** images show a new tool, a hard-to-see relationship, or a verification result. **Helpful** images can follow once the essentials are in place. A diagram is better than a screenshot when the learner needs to understand a rule rather than find a button. Reuse one image across nearby steps when it genuinely shows both actions.

## Capture rules

- Use one consistent practice document and realistic, clearly labeled *example* dimensions. Do not imply that those dimensions fit every FTC team's hardware.
- Crop to the relevant Onshape panel and model. Keep enough interface visible to identify the tab, tool, feature list, or unit setting.
- Add a short arrow or numbered callout to the exact control or geometry. Do not depend on color alone; use labels and alt text.
- For before and after comparisons, keep the camera angle and scale the same. Show the dimension or variable that changed.
- Hide account names, team documents, private links, and browser tabs before capture.
- Store approved images in `static/images/academy/onshape/` using the suggested lesson and step number, such as `1-3-d-04-symmetric-holes.png`. Add a descriptive `alt` and a one-sentence caption when attaching it to a step's `media` field.

## Course 1: Quick Start and CAD Mental Model

### Lesson 1.1 — How parametric CAD thinks

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 1.1.a Separate intent from shape | **Make:** simple bracket sketch with body, thickness, original holes, and second hole group labeled; no CAD controls. | Essential |
| 1.1.b Choose controlling values | **Make:** same bracket with arrows for width, height, thickness, hole spacing, diameter, and edge radius. Separate required values from examples. | Essential |
| 1.1.c Map the feature chain | **Make:** four-box flow: flat sketch → extruded solid → through holes → edge fillet/chamfer. Show small bracket at each stage. | Essential |
| 1.1.d Define relationships | **Make:** centerline with two mirrored hole centers and equal-diameter marks; label horizontal, vertical, and symmetric. Existing `construction-symmetry.svg` can be adapted. | Essential |
| 1.1.e Predict an edit | **Make:** paired before/after brackets at the same scale: width increases, hole spacing stays fixed, edges move outward. | Essential |

### Lesson 1.2 — Navigate and organize the workspace

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 1.2.a Create the document | **Screenshot:** document title and renamed Bracket Part Studio tab, with both called out. | Essential |
| 1.2.b Survey the tabs | **Screenshot:** bottom tab bar showing Part Studio and Assembly; label what each is for. | Essential |
| 1.2.c Set units | **Screenshot:** workspace units control and selected length unit; include one dimension showing the unit. | Essential |
| 1.2.d Practice view control | **Screenshot pair:** angled view and restored top view, with view cube and fit control visible. | Helpful |
| 1.2.e Apply naming conventions | **Screenshot:** feature list after renaming Base sketch, Bracket thickness, Mounting holes, Edge fillet. | Helpful |

### Lesson 1.3 — Create a fully defined base sketch

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 1.3.a Start at the origin | **Screenshot:** Sketch plane selection and visible origin, before drawing. Label plane and origin. | Essential |
| 1.3.b Draw the base profile | **Screenshot:** Center point rectangle tool and rectangle centered on the origin. | Essential |
| 1.3.c Add construction axes | **Screenshot:** dashed horizontal and vertical construction lines through the origin; show construction toggle. | Essential |
| 1.3.d Relate the primary holes | **Screenshot:** two hole circles or center points, centerline, and visible symmetry/equal relations. | Essential |
| 1.3.e Dimension the intent | **Screenshot pair:** under-constrained sketch, then fully constrained sketch with width, height, hole spacing, and diameter readable. Existing `under-vs-fully-constrained.svg` can accompany it. | Essential |

### Lesson 1.4 — Turn the sketch into a part

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 1.4.a Create the structural solid | **Screenshot:** Extrude dialog with outer profile selected and operation set to New; show resulting single part. | Essential |
| 1.4.b Set editable thickness | **Screenshot:** Extrude distance field with a unit; point to the depth that changes in the preview. | Helpful |
| 1.4.c Create the primary holes | **Screenshot pair:** through-cut setting and a reverse view proving both holes open on the back face. | Essential |
| 1.4.d Add the second pattern | **Screenshot:** top view with original and second hole groups labeled, including their distinct spacing dimensions. | Essential |
| 1.4.e Finish exposed edges | **Screenshot:** selected edges in Fillet or Chamfer dialog, plus close-up of resulting edge. | Helpful |

### Lesson 1.5 — Make the design configurable

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 1.5.a Create named variables | **Screenshot:** Variable feature or table showing the three names, values, and length units. Show names in their definition without `#`; uses in dimensions include `#`. | Essential |
| 1.5.b Reference bracket width | **Screenshot:** sketch width field containing `#bracketWidth`; show the referenced rectangle edge. | Essential |
| 1.5.c Reference thickness | **Screenshot:** Extrude distance field containing `#bracketThickness`. | Helpful |
| 1.5.d Reference hole spacing | **Screenshot:** dimension between hole centers containing `#primaryHoleSpacing`. | Essential |
| 1.5.e Run a configuration test | **Screenshot pair:** one variable before and after a change, with the same view and a clear callout to what moved. | Essential |

### Lesson 1.6 — Inspect, revise, and communicate

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 1.6.a Measure critical geometry | **Screenshot:** Measure panel and a selected hole edge plus nearest outer edge for minimum edge material. | Essential |
| 1.6.b Inspect every orientation | **Screenshot set:** top, underside, and isometric views of the same bracket. | Helpful |
| 1.6.c Confirm units and names | **Screenshot:** units indicator and clearly named feature list in one view if readable. | Helpful |
| 1.6.d Complete the challenge | **Screenshot pair:** original and revised second hole pattern; original holes visibly unchanged. | Essential |
| 1.6.e Prepare the record | **Make:** example submission image with a clean isometric capture and a short note listing format, units, and filename. | Helpful |

## Course 2: Parallel-Plate Drivetrain

### Lesson 2.1 — Establish the design brief and robot envelope

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 2.1.a Write the design brief | **Make:** filled one-page example with wheel count, drive style, service goal, manufacturing process, and allowed space. Label values as examples. | Essential |
| 2.1.b Build the specification table | **Make:** small table showing value, unit, source, and verified/provisional status; include one unknown. | Essential |
| 2.1.c Create named controls | **Screenshot:** Variable table or feature list with six controls and units. | Essential |
| 2.1.d Sketch the allocated envelope | **Screenshot:** centered rectangle in top view with maximum length and width dimensions tied to variables. | Essential |
| 2.1.e Mark hard and soft boundaries | **Make over screenshot:** construction zones for wheel sweep, frame edge, wiring, and tool access; distinguish fixed from provisional. | Essential |

### Lesson 2.2 — Create the master layout sketch

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 2.2.a Establish datums | **Screenshot:** longitudinal and transverse dashed centerlines through the origin, with names. | Essential |
| 2.2.b Place wheel axes | **Screenshot:** wheel-center points with symmetry and distance dimensions visible. | Essential |
| 2.2.c Represent wheel sweep | **Make over screenshot:** wheel sweep circles and a side-view width note; the top view alone cannot show width. | Essential |
| 2.2.d Place motor envelopes | **Screenshot:** simple motor body outline and output shaft axis, with source dimensions called out. | Essential |
| 2.2.e Locate plates and service zones | **Make over screenshot:** plate inner/outer faces and shaded access for tools and removable parts. | Essential |
| 2.2.f Test the layout | **Screenshot pair:** before/after track-width edit at the same scale, showing all paired wheel centers move correctly. | Helpful |

### Lesson 2.3 — Model the two drivetrain plates

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 2.3.a Define the plate perimeter | **Screenshot:** outline over master layout, with bearing and fastener edge material highlighted. | Essential |
| 2.3.b Create the first plate | **Screenshot:** extrusion as New part using plate-thickness variable and named Left plate result. | Essential |
| 2.3.c Create the matching plate | **Screenshot:** two parts in isometric view, with plate spacing dimension between the intended reference faces. | Essential |
| 2.3.d Add structural cutouts cautiously | **Make:** side-by-side plate with safe and unsafe cutout positions, showing load path around bearing and fastener regions. | Helpful |
| 2.3.e Add manufacturing edge treatments | **Screenshot:** selected edges and finished radii/chamfers that the chosen process can make. | Helpful |
| 2.3.f Verify paired updates | **Screenshot pair:** same view before/after a plate-spacing edit; include updated variable value. | Helpful |

### Lesson 2.4 — Add wheel, bearing, shaft, and motor interfaces

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 2.4.a Create bearing seats | **Screenshot:** section view of bearing seat, with outside diameter, width/depth, and intended fit note. | Essential |
| 2.4.b Represent shafts and wheels | **Screenshot:** simplified shaft and wheel cylinders with their common axis and mate connectors labeled. | Essential |
| 2.4.c Add motor interfaces | **Screenshot:** motor bolt pattern, output axis, and transparent simple motor envelope. | Essential |
| 2.4.d Add fastener holes | **Make over screenshot:** fastener hole plus head/nut/washer and tool clearance zones. | Essential |
| 2.4.e Propagate shared interfaces | **Screenshot:** matching holes across both plates, with a separate asymmetrical motor or service feature called out. | Helpful |
| 2.4.f Audit material and support | **Make:** force path from wheel through bearing and plate to frame; show minimum material around openings. Existing `safe-hole-edge.svg` may help. | Essential |

### Lesson 2.5 — Assemble, constrain, inspect, and review the drivetrain

| Step | Image to make or capture | Priority |
| --- | --- | --- |
| 2.5.a Start the assembly | **Screenshot:** Assembly tab, inserted parts list, and the one fixed base instance. | Essential |
| 2.5.b Constrain fixed hardware | **Screenshot:** Fastened mate dialog with two selected connector locations and the fixed result. | Essential |
| 2.5.c Preserve wheel rotation | **Screenshot or short GIF:** Revolute mate at wheel axis; mark the allowed rotation and forbidden sideways slide. | Essential |
| 2.5.d Inspect sections and interference | **Screenshot pair:** section through a bearing/shaft stack and Interference detection result, including a resolved example. | Essential |
| 2.5.e Perform a service sequence | **Make:** numbered exploded view: remove fastener → wheel → motor → plate; mark tool approach. | Essential |
| 2.5.f Complete the wider-wheel challenge | **Screenshot pair:** original and wider wheel inside the same outer boundary, with the narrowest gap labeled. | Essential |

## Attaching finished images

The lesson template already renders a step's `media` entries above its instructions. Add an entry such as:

```python
"media": ({
    "path": "images/academy/onshape/1-3-b-center-rectangle.png",
    "alt": "Onshape sketch with a rectangle centered on the origin; the Center point rectangle tool is selected.",
    "caption": "Click the origin for the rectangle center, then set a corner.",
},),
```

Capture the essential images first. Several conceptual images can be created from the existing Academy SVGs; Onshape screenshots should be taken from the actual practice model so the feature names, dimensions, and sequence match the lessons.
