"""Keep the reference CLI aligned with authenticated generated fight windows."""
import contextlib
import io
from pathlib import Path
import re
import runpy
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2.generate_first_fight import WINDOWS


class BatchCliTests(unittest.TestCase):
    def test_first_fight_safety_horizon_retains_twenty_seconds_and_covers_later_boundary(self):
        import ast
        import copy
        import inspect
        from tools.mk2 import batch_reference as batch
        tree=ast.parse(inspect.getsource(batch.capture))
        command=copy.deepcopy(next(node for node in ast.walk(tree)
            if isinstance(node,ast.FunctionDef) and node.name=='command'))
        # Execute the actual argument transformation before script/filesystem work.
        command.body=[command.body[0],ast.Return(value=ast.Name(id='args',ctx=ast.Load()))]
        scope=dict(first_fight_window=84,selection_window=None,start_release=False,
                   start_input=False,prestart_window=None,next_wait=False)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[command],type_ignores=[])),
                     '<capture command contract>','exec'),scope)
        for end,seconds in ((110030700,'20'),(118028828,'20'),(126026668,'22')):
            scope['selected']={'end':end}
            self.assertEqual(scope['command'](['mame','-seconds_to_run','1','-nothrottle'],Path('unused')),
                             ['mame','-seconds_to_run',seconds,'-nothrottle'])

    def test_first_fight_choices_follow_generated_windows(self):
        output=io.StringIO()
        with patch.object(sys,'argv',['batch_reference.py','--help']),contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(Path(__file__).with_name('batch_reference.py')),run_name='__main__')
        self.assertEqual(stopped.exception.code,0)
        choices=re.search(r'--first-fight-window\s+\{([^}]+)\}',output.getvalue())
        self.assertIsNotNone(choices)
        self.assertEqual([int(value) for value in choices.group(1).split(',')],list(range(len(WINDOWS))))


if __name__=='__main__':unittest.main()
