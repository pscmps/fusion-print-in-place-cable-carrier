import adsk.core
import adsk.fusion
import traceback
import os
import math


PROJECT_DIR = os.path.join(os.path.expanduser('~'), 'Documents', 'SG90_Cable_Carrier_Output')
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'cad')
LOG_DIR = os.path.join(PROJECT_DIR, 'logs')
DEFAULT_PARAMETERS = {
    'cable_width_mm': 10.0,
    'cable_height_mm': 6.0,
    'stroke_mm': 200.0,
    'link_pitch_mm': 20.0,
}


def output_paths(parameters):
    width = parameters['cable_width_mm']
    height = parameters['cable_height_mm']
    stroke = parameters['stroke_mm']
    pitch = parameters['link_pitch_mm']
    suffix = 'W{:g}_H{:g}_L{:g}_P{:g}_chamfer1x1_printcomponent'.format(width, height, stroke, pitch).replace('.', 'p')
    base_name = 'SG90_PIP_Cable_Carrier_' + suffix
    return (
        os.path.join(OUTPUT_DIR, base_name + '.f3d'),
        os.path.join(OUTPUT_DIR, base_name + '.step'),
        os.path.join(LOG_DIR, base_name + '_build.log'),
    )


OUTPUT_F3D, OUTPUT_STEP, LOG_FILE = output_paths(DEFAULT_PARAMETERS)


def mm(value):
    return adsk.core.ValueInput.createByReal(value / 10.0)


def write_log(message, log_file=LOG_FILE):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(log_file, 'a', encoding='utf-8') as stream:
        stream.write(message + '\n')


def add_offset_plane(component, base_plane, offset_mm, name):
    plane_input = component.constructionPlanes.createInput()
    plane_input.setByOffset(base_plane, mm(offset_mm))
    plane = component.constructionPlanes.add(plane_input)
    plane.name = name
    return plane


def add_rectangle(sketch, x1, y1, x2, y2):
    lines = sketch.sketchCurves.sketchLines
    p1 = adsk.core.Point3D.create(x1 / 10.0, y1 / 10.0, 0)
    p2 = adsk.core.Point3D.create(x2 / 10.0, y2 / 10.0, 0)
    lines.addTwoPointRectangle(p1, p2)


def add_polygon(sketch, points):
    lines = sketch.sketchCurves.sketchLines
    pts = [adsk.core.Point3D.create(a / 10.0, b / 10.0, 0) for a, b in points]
    for index in range(len(pts)):
        lines.addByTwoPoints(pts[index], pts[(index + 1) % len(pts)])


def all_profiles(sketch):
    profiles = adsk.core.ObjectCollection.create()
    for index in range(sketch.profiles.count):
        profiles.add(sketch.profiles.item(index))
    return profiles


def extrude_profiles(component, sketch, distance_mm, operation, name, participant_bodies=None):
    features = component.features.extrudeFeatures
    profiles = all_profiles(sketch)
    ext_input = features.createInput(profiles, operation)
    ext_input.setDistanceExtent(False, mm(distance_mm))
    if participant_bodies is not None:
        ext_input.participantBodies = participant_bodies
    feature = features.add(ext_input)
    feature.name = name
    return feature


def loft_profiles(component, first_sketch, second_sketch, operation, name, participant_bodies=None):
    lofts = component.features.loftFeatures
    loft_input = lofts.createInput(operation)
    loft_input.loftSections.add(first_sketch.profiles.item(0))
    loft_input.loftSections.add(second_sketch.profiles.item(0))
    if participant_bodies is not None:
        loft_input.participantBodies = participant_bodies
    feature = lofts.add(loft_input)
    feature.name = name
    return feature


def revolve_polygon(component, plane, points, axis_start, axis_end, operation, name):
    sketch = component.sketches.add(plane)
    sketch.name = name + '_Profile'
    add_polygon(sketch, points)
    axis = sketch.sketchCurves.sketchLines.addByTwoPoints(
        adsk.core.Point3D.create(axis_start[0] / 10.0, axis_start[1] / 10.0, 0),
        adsk.core.Point3D.create(axis_end[0] / 10.0, axis_end[1] / 10.0, 0),
    )
    axis.isConstruction = True
    revolves = component.features.revolveFeatures
    revolve_input = revolves.createInput(sketch.profiles.item(0), axis, operation)
    revolve_input.setAngleExtent(False, adsk.core.ValueInput.createByReal(math.pi * 2.0))
    feature = revolves.add(revolve_input)
    feature.name = name
    return feature


def add_circle_sketch(component, plane, center_x_mm, center_z_mm, radius_mm, name):
    sketch = component.sketches.add(plane)
    sketch.name = name
    sketch.sketchCurves.sketchCircles.addByCenterRadius(
        adsk.core.Point3D.create(center_x_mm / 10.0, -center_z_mm / 10.0, 0),
        radius_mm / 10.0,
    )
    return sketch


def add_user_parameter(design, name, expression, units, comment):
    existing = design.userParameters.itemByName(name)
    if existing:
        return existing
    return design.userParameters.add(name, adsk.core.ValueInput.createByString(expression), units, comment)


def validate_parameters(parameters):
    width = parameters['cable_width_mm']
    height = parameters['cable_height_mm']
    stroke = parameters['stroke_mm']
    pitch = parameters['link_pitch_mm']
    if width < 6.0:
        raise ValueError('Cable width must be at least 6 mm')
    if height < width / 2.0 + 0.6:
        raise ValueError('Cable height must be at least width / 2 + 0.6 mm to keep the hook underside at 45 degrees')
    if stroke < pitch:
        raise ValueError('Stroke must be at least one link pitch')
    if pitch < 12.0:
        raise ValueError('Link pitch must be at least 12 mm')


def build_link(root, index, parameters, log_file):
    pitch_mm = parameters['link_pitch_mm']
    cable_width_mm = parameters['cable_width_mm']
    cable_height_mm = parameters['cable_height_mm']
    floor_thickness = 2.0
    wall_thickness = 2.0
    hinge_zone = 4.0
    ear_width = 1.7
    tab_overlap = 0.20
    hinge_support_x_overlap = 1.00
    hinge_support_y_overlap = 0.20
    outer_half = cable_width_mm / 2.0 + wall_thickness
    clear_half = cable_width_mm / 2.0
    ear_inner = outer_half - ear_width
    front_barrel_inner = clear_half - ear_width
    wall_top = floor_thickness + cable_height_mm
    hinge_center_z = floor_thickness + cable_height_mm / 2.0
    channel_start = hinge_zone
    channel_end = pitch_mm - hinge_zone
    channel_length = channel_end - channel_start
    hook_length = channel_length / 3.0

    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(index * pitch_mm / 10.0, 0, 0)
    occurrence = root.occurrences.addNewComponent(transform)
    component = occurrence.component
    component.name = 'Link_{:02d}'.format(index + 1)

    # Main open channel: 10 mm clear width, 6 mm clear height.  The full-width
    # floor stops before both hinge zones so it cannot fuse to the neighboring
    # link. Separate side tabs support the left and right hinge pairs while
    # keeping the center open for the servo cable.
    floor_sketch = component.sketches.add(component.xYConstructionPlane)
    floor_sketch.name = 'Floor_Profile'
    add_rectangle(floor_sketch, channel_start, -outer_half, channel_end, outer_half)
    extrude_profiles(component, floor_sketch, floor_thickness, adsk.fusion.FeatureOperations.NewBodyFeatureOperation, 'Floor_2mm')

    tab_sketch = component.sketches.add(component.xYConstructionPlane)
    tab_sketch.name = 'Hinge_Connection_Tabs'
    # 0.2 mm overlap with the main floor guarantees a single connected body.
    add_rectangle(tab_sketch, 0, -outer_half, channel_start + tab_overlap, -ear_inner)
    add_rectangle(tab_sketch, 0, ear_inner, channel_start + tab_overlap, outer_half)
    # Overlap the front tabs 0.20 mm into the side walls in Y as well as X.
    # The former boundary at +/-clear_half was only a line contact in top view.
    add_rectangle(tab_sketch, channel_end - tab_overlap, -clear_half - tab_overlap, pitch_mm, -front_barrel_inner)
    add_rectangle(tab_sketch, channel_end - tab_overlap, front_barrel_inner, pitch_mm, clear_half + tab_overlap)
    extrude_profiles(component, tab_sketch, floor_thickness, adsk.fusion.FeatureOperations.JoinFeatureOperation, 'Hinge_Connection_Tabs_Overlap0p20')

    # Remove a 1 x 1 mm triangular prism from each cable-side upper edge.
    # The resulting face is an exact 45-degree chamfer and increases entry
    # clearance when a narrow cable channel is selected.
    chamfer_plane = add_offset_plane(
        component,
        component.yZConstructionPlane,
        channel_end - tab_overlap,
        'Front_Tab_Chamfer_Start',
    )
    chamfer_sketch = component.sketches.add(chamfer_plane)
    chamfer_sketch.name = 'Front_Tab_Inner_Edge_Chamfer_1x1'
    add_polygon(chamfer_sketch, [
        (-floor_thickness, -front_barrel_inner),
        (-(floor_thickness - 1.0), -front_barrel_inner),
        (-floor_thickness, -front_barrel_inner - 1.0),
    ])
    add_polygon(chamfer_sketch, [
        (-floor_thickness, front_barrel_inner),
        (-floor_thickness, front_barrel_inner + 1.0),
        (-(floor_thickness - 1.0), front_barrel_inner),
    ])
    extrude_profiles(
        component,
        chamfer_sketch,
        pitch_mm - (channel_end - tab_overlap),
        adsk.fusion.FeatureOperations.CutFeatureOperation,
        'Front_Tab_Cable_Edge_Chamfer_1x1_45deg',
        [component.bRepBodies.item(0)],
    )

    wall_sketch = component.sketches.add(component.xYConstructionPlane)
    wall_sketch.name = 'Side_Wall_Profiles'
    add_rectangle(wall_sketch, channel_start, -outer_half, channel_end, -clear_half)
    add_rectangle(wall_sketch, channel_start, clear_half, channel_end, outer_half)
    extrude_profiles(component, wall_sketch, wall_top, adsk.fusion.FeatureOperations.JoinFeatureOperation, 'Side_Walls')

    # Split the 12 mm open-channel length into thirds: a 4 mm retaining hook,
    # a 4 mm unobstructed loading gap, then a 4 mm hook from the opposite side.
    # Every link uses the same orientation, keeping the chain to one part type.
    # Both hooks cross the centerline by 0.8 mm and retain the same exact
    # support-free 45-degree underside.
    hook_peak_under = wall_top + 0.6
    hook_inner_under = hook_peak_under - (clear_half + 0.8)
    hook_outer_low = hook_inner_under - 0.6
    hook_top = wall_top + 1.0
    left_hook_profile = [(-hook_outer_low, -clear_half - 0.8), (-hook_inner_under, -clear_half), (-hook_peak_under, 0.8), (-hook_top, 0.4), (-hook_top, -clear_half - 0.8)]
    right_hook_profile = [(-hook_outer_low, clear_half + 0.8), (-hook_inner_under, clear_half), (-hook_peak_under, -0.8), (-hook_top, -0.4), (-hook_top, clear_half + 0.8)]
    hook_sections = [(channel_start, left_hook_profile, 'Left'), (channel_start + 2.0 * hook_length, right_hook_profile, 'Right')]
    for x_start, hook_profile, side_name in hook_sections:
        hook_plane = add_offset_plane(component, component.yZConstructionPlane, x_start, 'Hook_{}_Start_x{}'.format(side_name, x_start))
        hook_sketch = component.sketches.add(hook_plane)
        hook_sketch.name = 'Snap_Hook_{}_Third'.format(side_name)
        # On Fusion's YZ plane sketch X maps to model Z, and sketch Y to model Y.
        add_polygon(hook_sketch, hook_profile)
        extrude_profiles(component, hook_sketch, hook_length, adsk.fusion.FeatureOperations.JoinFeatureOperation, 'Snap_Hook_{}_Third'.format(side_name))

    # Rear female ears. Only the face adjacent to the preceding link is
    # relieved. At hinge-center height (Z=5) it leaves 0.50 mm clearance from
    # that link's wall, then recedes at 45 degrees both upward and downward.
    # No separate relief hole is used.
    # Fusion's XZ sketch Y-axis points toward negative model Z.  Negative
    # sketch values therefore place the hinge above the common Z=0 bed.
    relief = cable_height_mm / 2.0
    hinge_profile = [(0.5, -1), (hinge_zone, -1), (hinge_zone, -wall_top), (-0.5, -wall_top), (-0.5 - relief, -hinge_center_z)]
    for side_name, y_start in [('Left', -outer_half), ('Right', ear_inner)]:
        ear_plane = add_offset_plane(component, component.xZConstructionPlane, y_start, 'Rear_Ear_{}_Plane'.format(side_name))
        ear_sketch = component.sketches.add(ear_plane)
        ear_sketch.name = 'Rear_Ear_{}_45deg'.format(side_name)
        add_polygon(ear_sketch, hinge_profile)
        extrude_profiles(component, ear_sketch, 1.7, adsk.fusion.FeatureOperations.JoinFeatureOperation, 'Rear_Ear_{}'.format(side_name))
        own_link_body = component.bRepBodies.item(0)

        # Cut a true conical receiving hole that follows the complete 45-degree
        # pin surface. The pin is R2.30 at its root and its apex extends 0.30 mm
        # beyond the ear outer face. Adding 0.30 mm radially at both bore ends
        # creates a parallel 45-degree bore with uniform clearance.
        pin_hole_clearance = 0.30
        pin_radius_at_outer_plane = 0.30
        pin_radius_at_ear_inner = 2.00
        outer_bore_radius = pin_radius_at_outer_plane + pin_hole_clearance
        inner_bore_radius = pin_radius_at_ear_inner + pin_hole_clearance
        if side_name == 'Left':
            outer_circle = add_circle_sketch(component, ear_plane, 0, hinge_center_z, outer_bore_radius, 'Rear_Bore_Left_Outer_R0p60')
            inner_plane = add_offset_plane(component, component.xZConstructionPlane, -ear_inner, 'Rear_Bore_Left_Inner_Plane')
            inner_circle = add_circle_sketch(component, inner_plane, 0, hinge_center_z, inner_bore_radius, 'Rear_Bore_Left_Inner_R2p30')
            loft_profiles(component, outer_circle, inner_circle, adsk.fusion.FeatureOperations.CutFeatureOperation, 'Rear_Bore_Left_Conical_45deg_Gap0p3', [own_link_body])
        else:
            inner_plane = add_offset_plane(component, component.xZConstructionPlane, ear_inner, 'Rear_Bore_Right_Inner_Plane')
            inner_circle = add_circle_sketch(component, inner_plane, 0, hinge_center_z, inner_bore_radius, 'Rear_Bore_Right_Inner_R2p30')
            outer_plane = add_offset_plane(component, component.xZConstructionPlane, outer_half, 'Rear_Bore_Right_Outer_Plane')
            outer_circle = add_circle_sketch(component, outer_plane, 0, hinge_center_z, outer_bore_radius, 'Rear_Bore_Right_Outer_R0p60')
            loft_profiles(component, inner_circle, outer_circle, adsk.fusion.FeatureOperations.CutFeatureOperation, 'Rear_Bore_Right_Conical_45deg_Gap0p3', [own_link_body])

    # Two side-mounted male barrels leave a 6.6 mm unobstructed center passage.
    # The next link's outer female ears surround the conical pins with 0.30 mm
    # profile clearance. The face adjacent to the next link has the matching
    # Z=5 minimum gap and 45-degree upper/lower rotational clearance. The
    # 0.30 mm axial gap between ear and barrel is retained.
    # Extend the hinge support itself 1.00 mm left into the side wall. Its
    # extrusion also crosses the wall boundary by 0.20 mm in Y. This creates a
    # real overlapping volume; the support no longer meets the wall only at
    # the cross-shaped edge visible in top view.
    front_support_start = channel_end - hinge_support_x_overlap
    front_profile = [(front_support_start, -1), (pitch_mm - 0.5, -1), (pitch_mm + 0.5 + relief, -hinge_center_z), (pitch_mm + 0.5, -wall_top), (front_support_start, -wall_top)]
    front_barrel_span = ear_width + hinge_support_y_overlap
    for side_name, y_start in [('Left', -clear_half - hinge_support_y_overlap), ('Right', front_barrel_inner)]:
        barrel_plane = add_offset_plane(component, component.xZConstructionPlane, y_start, 'Front_Barrel_{}_Plane'.format(side_name))
        barrel_sketch = component.sketches.add(barrel_plane)
        barrel_sketch.name = 'Front_Barrel_{}_45deg'.format(side_name)
        add_polygon(barrel_sketch, front_profile)
        extrude_profiles(component, barrel_sketch, front_barrel_span, adsk.fusion.FeatureOperations.JoinFeatureOperation, 'Front_Barrel_{}_Overlap1p00'.format(side_name))

    # Revolve exact triangular cross-sections so each pin reaches a true apex.
    # The visible cone is R2.30 at the barrel face and reaches the apex 2.30 mm
    # later, giving an exact 45-degree surface. Extend that same cone 0.10 mm
    # into the barrel (R2.40 construction root) so the Join operation has real
    # overlap instead of a coincident face. The apex protrudes 0.30 mm beyond
    # the female ear outer face; there is no truncated nose or cylindrical cap.
    pin_profile_plane = add_offset_plane(component, component.yZConstructionPlane, pitch_mm, 'Pin_Profile')
    revolve_polygon(
        component,
        pin_profile_plane,
        [(-hinge_center_z, -clear_half + 0.1), (-hinge_center_z - 2.4, -clear_half + 0.1), (-hinge_center_z, -outer_half - 0.3)],
        (-hinge_center_z, -clear_half + 0.1),
        (-hinge_center_z, -outer_half - 0.3),
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        'Left_Pin_Full_Apex_45deg',
    )
    revolve_polygon(
        component,
        pin_profile_plane,
        [(-hinge_center_z, clear_half - 0.1), (-hinge_center_z - 2.4, clear_half - 0.1), (-hinge_center_z, outer_half + 0.3)],
        (-hinge_center_z, clear_half - 0.1),
        (-hinge_center_z, outer_half + 0.3),
        adsk.fusion.FeatureOperations.JoinFeatureOperation,
        'Right_Pin_Full_Apex_45deg',
    )

    # Keep the browser concise and useful.
    body_count = component.bRepBodies.count
    if body_count != 1:
        for inspect_index in range(body_count):
            inspect_body = component.bRepBodies.item(inspect_index)
            inspect_box = inspect_body.boundingBox
            write_log(
                'BODY Link_{:02d} #{} x={:.2f}..{:.2f} y={:.2f}..{:.2f} z={:.2f}..{:.2f}mm'.format(
                    index + 1,
                    inspect_index + 1,
                    inspect_box.minPoint.x * 10.0,
                    inspect_box.maxPoint.x * 10.0,
                    inspect_box.minPoint.y * 10.0,
                    inspect_box.maxPoint.y * 10.0,
                    inspect_box.minPoint.z * 10.0,
                    inspect_box.maxPoint.z * 10.0,
                ), log_file
            )
        raise RuntimeError('Link_{:02d} is not one connected body ({} bodies)'.format(index + 1, body_count))
    body = component.bRepBodies.item(0)
    body.name = 'Printable_Link_{:02d}'.format(index + 1)
    min_z_mm = body.boundingBox.minPoint.z * 10.0
    if min_z_mm < -0.01:
        raise RuntimeError('Link_{:02d} extends below the print bed: {:.3f} mm'.format(index + 1, min_z_mm))
    write_log('CHECK Link_{:02d} bodies=1 minZ={:.3f}mm'.format(index + 1, min_z_mm), log_file)
    return occurrence


def generate(parameters=None):
    parameters = dict(DEFAULT_PARAMETERS if parameters is None else parameters)
    validate_parameters(parameters)
    output_f3d, output_step, log_file = output_paths(parameters)
    link_pitch = parameters['link_pitch_mm']
    stroke = parameters['stroke_mm']
    cable_width = parameters['cable_width_mm']
    cable_height = parameters['cable_height_mm']
    link_count = int(math.ceil(stroke / link_pitch)) + 1
    try:
        app = adsk.core.Application.get()
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        if os.path.exists(log_file):
            os.remove(log_file)
        write_log('START', log_file)
        write_log('PARAM width={:g} height={:g} stroke={:g} pitch={:g} links={}'.format(
            cable_width, cable_height, stroke, link_pitch, link_count), log_file)

        document = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.designType = adsk.fusion.DesignTypes.ParametricDesignType
        root = design.rootComponent

        add_user_parameter(design, 'LinkPitch', '{:g} mm'.format(link_pitch), 'mm', 'Joint-to-joint pitch')
        add_user_parameter(design, 'MovingStroke', '{:g} mm'.format(stroke), 'mm', 'Target moving stroke')
        add_user_parameter(design, 'LinkCount', str(link_count), '', 'Automatically calculated as ceil(stroke / pitch) + 1')
        add_user_parameter(design, 'PinHoleClearance', '0.30 mm', 'mm', 'Uniform radial gap between the full conical pin and bore')
        add_user_parameter(design, 'BoreInnerRadius', '2.30 mm', 'mm', 'Conical bore radius at the inner ear face')
        add_user_parameter(design, 'BoreOuterRadius', '0.60 mm', 'mm', 'Conical bore radius at the outer ear face')
        add_user_parameter(design, 'PIPAxialGap', '0.30 mm', 'mm', 'Axial gap between neighboring hinge ear and barrel')
        add_user_parameter(design, 'CableClearWidth', '{:g} mm'.format(cable_width), 'mm', 'Cable channel clear width')
        add_user_parameter(design, 'CableClearHeight', '{:g} mm'.format(cable_height), 'mm', 'Cable channel clear height')
        add_user_parameter(design, 'HingeCablePassage', '{:g} mm'.format(cable_width - 3.4), 'mm', 'Clear passage between the left and right hinge barrels')
        add_user_parameter(design, 'SupportSlope', '45 deg', 'deg', 'Self-supporting lower hinge slope')
        add_user_parameter(design, 'PinAndBoreSlope', '45 deg', 'deg', 'Matched root-to-tip support-free pin and bore slope')
        add_user_parameter(design, 'PinRadiusAtBarrelFace', '2.30 mm', 'mm', 'Visible pin radius at the barrel outer face')
        add_user_parameter(design, 'PinConstructionRootRadius', '2.40 mm', 'mm', 'Cone radius 0.10 mm inside the barrel for reliable body join')
        add_user_parameter(design, 'PinApexRadius', '0 mm', 'mm', 'True conical apex without a cylindrical cap')
        add_user_parameter(design, 'PinConeLength', '2.40 mm', 'mm', 'Full cone length including 0.10 mm overlap inside the barrel')
        add_user_parameter(design, 'PinApexProtrusion', '0.30 mm', 'mm', 'Apex projection beyond the female ear outer face')
        add_user_parameter(design, 'RotationalGap', '0.50 mm', 'mm', 'Minimum neighboring-wall gap at hinge-center height')
        add_user_parameter(design, 'HookCenterOverlap', '0.80 mm', 'mm', 'Opposed third-width hook overlap beyond channel centerline')
        add_user_parameter(design, 'HookSectionLength', '{:g} mm'.format((link_pitch - 8.0) / 3.0), 'mm', 'One third of the open-channel length')
        add_user_parameter(design, 'WallTabOverlap', '0.20 mm', 'mm', 'Front and rear hinge tabs overlap the side walls in plan view')
        add_user_parameter(design, 'HingeSupportXOverlap', '1.00 mm', 'mm', 'Front hinge support extension into the side wall in the link direction')
        add_user_parameter(design, 'HingeSupportYOverlap', '0.20 mm', 'mm', 'Front hinge support overlap across the side-wall boundary')
        add_user_parameter(design, 'CableEdgeChamfer', '1.00 mm', 'mm', 'Equal-distance 45-degree chamfer on the front tab cable-side upper edges')
        add_user_parameter(design, 'LinkPartTypes', '1', '', 'All links use the same hook orientation and geometry')

        link_occurrences = []
        for index in range(link_count):
            link_occurrences.append(build_link(root, index, parameters, log_file))
            write_log('BUILT Link_{:02d}'.format(index + 1), log_file)
            adsk.doEvents()

        # A later link's bore must never cut the already-created neighboring
        # pin. Validate the completed assembly, not only each link at creation.
        for index in range(root.occurrences.count):
            occurrence = root.occurrences.item(index)
            final_body_count = occurrence.component.bRepBodies.count
            write_log('FINAL_CHECK {} bodies={}'.format(occurrence.name, final_body_count), log_file)
            if final_body_count != 1:
                raise RuntimeError('{} ended with {} bodies; a later cut affected its pin'.format(occurrence.name, final_body_count))

        # Keep the print-in-place links as separate bodies, but collect all of
        # them under one component for slicer export and simple human handling.
        print_occurrence = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        print_component = print_occurrence.component
        print_component.name = 'PRINT_SG90_Cable_Carrier'
        for index, occurrence in enumerate(link_occurrences):
            source_body = occurrence.component.bRepBodies.item(0)
            moved_body = source_body.moveToComponent(print_occurrence)
            if not moved_body:
                raise RuntimeError('Failed to move Link_{:02d} into print component'.format(index + 1))
            moved_body.name = 'Printable_Link_{:02d}'.format(index + 1)
        for occurrence in reversed(link_occurrences):
            occurrence.deleteMe()
        final_print_body_count = print_component.bRepBodies.count
        write_log('PRINT_COMPONENT name={} bodies={}'.format(print_component.name, final_print_body_count), log_file)
        if root.occurrences.count != 1 or final_print_body_count != link_count:
            raise RuntimeError('Print hierarchy invalid: root occurrences={}, print bodies={}'.format(root.occurrences.count, final_print_body_count))

        document.name = 'SG90_PIP_Cable_Carrier_W{:g}_H{:g}_L{:g}_P{:g}'.format(cable_width, cable_height, stroke, link_pitch)
        export_manager = design.exportManager
        f3d_options = export_manager.createFusionArchiveExportOptions(output_f3d)
        export_manager.execute(f3d_options)
        step_options = export_manager.createSTEPExportOptions(output_step, print_component)
        export_manager.execute(step_options)
        write_log('EXPORTED ' + output_f3d, log_file)
        write_log('EXPORTED ' + output_step, log_file)
        write_log('DONE', log_file)

        app.activeViewport.fit()
        result = {
            'document': document.name,
            'link_count': link_count,
            'f3d': output_f3d,
            'step': output_step,
            'log': log_file,
        }
        print('SG90 cable carrier created: {} links, W{:g} H{:g} L{:g} P{:g}'.format(link_count, cable_width, cable_height, stroke, link_pitch))
        print('Saved F3D: ' + output_f3d)
        print('Saved STEP: ' + output_step)
        return result
    except Exception:
        error_text = traceback.format_exc()
        write_log('ERROR\n' + error_text, log_file)
        raise


def run(context):
    return generate(DEFAULT_PARAMETERS)


def stop(context):
    pass
