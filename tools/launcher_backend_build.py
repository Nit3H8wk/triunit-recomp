"""Build-only dependencies shared by launcher targets."""
from pathlib import Path

def arguments(root):
    root=Path(root)
    return ['-I'+str(root/'native/include'),'-I'+str(root/'native/mk2'),
            str(root/'native/mk2/mk2_profile.cpp'),str(root/'native/mk2/mk2_program.cpp'),
            str(root/'native/launcher/launcher_operator.cpp'),str(root/'native/src/mk5_program.cpp'),
            '-lbcrypt','-lwinmm','-lmfreadwrite','-lmfplat','-lmfuuid','-lxaudio2_9']
