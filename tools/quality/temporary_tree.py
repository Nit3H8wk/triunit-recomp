"""Audit/remove only a known project temporary tree without following links."""
from pathlib import Path
import os
def verified_tree(target:Path,parent:Path):
    target=target.absolute();parent=parent.absolute()
    assert target.parent==parent and target.name.startswith('temporary-')
    for p in [parent,*parent.parents,target]:
        assert not p.is_symlink() and not p.is_junction(),f'linked ancestor {p}'
    files=[];dirs=[];stack=[target]
    while stack:
        folder=stack.pop();dirs.append(folder)
        with os.scandir(folder) as entries:
            for entry in entries:
                p=Path(entry.path)
                assert not p.is_symlink() and not p.is_junction(),f'linked descendant {p}'
                if entry.is_dir(follow_symlinks=False):stack.append(p)
                else:files.append(p)
    return files,dirs
def remove_tree(target:Path,parent:Path):
    files,dirs=verified_tree(target,parent)
    count=sum(p.stat().st_size for p in files)
    for p in files:p.unlink()
    for p in reversed(dirs):p.rmdir()
    return {'target':str(target),'bytes_removed':count,'exists_after':target.exists(),'links_or_junctions':False,'traversal':'explicit scandir, reject link before descent'}
