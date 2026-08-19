import adsk.core
import adsk.fusion
import importlib.util
import os
import traceback


COMMAND_ID = 'pscmps_sg90_cable_carrier_generator'
COMMAND_NAME = 'ケーブルキャリア生成 / Cable Carrier Generator'
COMMAND_DESCRIPTION = '寸法指定でPrint-in-Placeケーブルキャリアを生成します。 / Generate a dimensioned print-in-place cable carrier.'
WORKSPACE_ID = 'FusionSolidEnvironment'
PANEL_CANDIDATES = ['SolidScriptsAddinsPanel', 'SolidCreatePanel']

_handlers = []
_panel_id = None


def _generator_path():
    candidates = [
        os.path.join(os.path.dirname(__file__), 'SG90_Cable_Carrier.py'),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError('SG90_Cable_Carrier.py が見つかりません。 / Generator core was not found.')


def _load_generator():
    path = _generator_path()
    spec = importlib.util.spec_from_file_location('sg90_cable_carrier_generator_core', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _value_mm(inputs, input_id):
    value_input = adsk.core.ValueCommandInput.cast(inputs.itemById(input_id))
    return value_input.value * 10.0


class GenerateExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        ui = adsk.core.Application.get().userInterface
        try:
            inputs = args.command.commandInputs
            parameters = {
                'cable_width_mm': _value_mm(inputs, 'cable_width'),
                'cable_height_mm': _value_mm(inputs, 'cable_height'),
                'stroke_mm': _value_mm(inputs, 'stroke'),
                'link_pitch_mm': _value_mm(inputs, 'link_pitch'),
            }
            result = _load_generator().generate(parameters)
            ui.messageBox(
                '生成が完了しました。 / Generation completed.\n\n'
                'リンク数 / Links: {}\nFusion: {}\nSTEP: {}'.format(
                    result['link_count'], result['f3d'], result['step']
                ),
                COMMAND_NAME,
            )
        except Exception:
            ui.messageBox('生成に失敗しました。 / Generation failed.\n\n' + traceback.format_exc(), COMMAND_NAME)


class GenerateValidateHandler(adsk.core.ValidateInputsEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            width = _value_mm(inputs, 'cable_width')
            height = _value_mm(inputs, 'cable_height')
            stroke = _value_mm(inputs, 'stroke')
            pitch = _value_mm(inputs, 'link_pitch')
            args.areInputsValid = width >= 6.0 and height >= width / 2.0 + 0.6 and pitch >= 12.0 and stroke >= pitch
        except Exception:
            args.areInputsValid = False


class GenerateCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        command = args.command
        command.isExecutedWhenPreEmpted = False
        command.setDialogInitialSize(520, 390)
        command.setDialogMinimumSize(500, 370)
        inputs = command.commandInputs
        inputs.addTextBoxCommandInput(
            'description', '',
            '寸法を入力してください。リンク数は自動計算されます。 / Enter dimensions; link count is calculated automatically.',
            1, True,
        )
        inputs.addValueInput('cable_width', '通路幅 / Channel width', 'mm', adsk.core.ValueInput.createByString('10 mm'))
        inputs.addValueInput('cable_height', '通路高さ / Channel height', 'mm', adsk.core.ValueInput.createByString('6 mm'))
        inputs.addValueInput('stroke', '長さ / Stroke length', 'mm', adsk.core.ValueInput.createByString('200 mm'))
        inputs.addValueInput('link_pitch', '1ブロック / Link pitch', 'mm', adsk.core.ValueInput.createByString('20 mm'))
        inputs.addTextBoxCommandInput(
            'constraints', '入力条件 / Limits',
            '幅≥6 / Width≥6 mm　高さ≥幅÷2+0.6 / Height≥Width÷2+0.6 mm\nブロック≥12 / Pitch≥12 mm　長さ≥ブロック / Length≥Pitch',
            2, True,
        )

        execute_handler = GenerateExecuteHandler()
        command.execute.add(execute_handler)
        _handlers.append(execute_handler)
        validate_handler = GenerateValidateHandler()
        command.validateInputs.add(validate_handler)
        _handlers.append(validate_handler)


def _find_panel(ui):
    workspace = ui.workspaces.itemById(WORKSPACE_ID)
    if not workspace:
        return None
    for panel_id in PANEL_CANDIDATES:
        panel = workspace.toolbarPanels.itemById(panel_id)
        if panel:
            return panel
    return None


def run(context):
    global _panel_id
    ui = adsk.core.Application.get().userInterface
    try:
        command_definition = ui.commandDefinitions.itemById(COMMAND_ID)
        if not command_definition:
            command_definition = ui.commandDefinitions.addButtonDefinition(COMMAND_ID, COMMAND_NAME, COMMAND_DESCRIPTION)
        created_handler = GenerateCommandCreatedHandler()
        command_definition.commandCreated.add(created_handler)
        _handlers.append(created_handler)

        panel = _find_panel(ui)
        if not panel:
            raise RuntimeError('配置先パネルが見つかりません。 / Fusion toolbar panel was not found.')
        _panel_id = panel.id
        if not panel.controls.itemById(COMMAND_ID):
            control = panel.controls.addCommand(command_definition)
            control.isPromoted = True
            control.isPromotedByDefault = True
    except Exception:
        ui.messageBox('アドインの開始に失敗しました。 / Add-in startup failed.\n\n' + traceback.format_exc(), COMMAND_NAME)


def stop(context):
    ui = adsk.core.Application.get().userInterface
    try:
        if _panel_id:
            workspace = ui.workspaces.itemById(WORKSPACE_ID)
            panel = workspace.toolbarPanels.itemById(_panel_id) if workspace else None
            control = panel.controls.itemById(COMMAND_ID) if panel else None
            if control:
                control.deleteMe()
        command_definition = ui.commandDefinitions.itemById(COMMAND_ID)
        if command_definition:
            command_definition.deleteMe()
        _handlers.clear()
    except Exception:
        pass
