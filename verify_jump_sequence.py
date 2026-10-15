"""Check grouped happy jumps and horizontal free-roam movement."""
from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from desktop_pet import DesktopPet


def main():
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    far=QPoint(-10000,-10000)
    with tempfile.TemporaryDirectory() as folder:
        pet=DesktopPet(Path(folder)/'settings.json',start_timer=False)
        pet.interactions.sleep_enabled=pet.interactions.rare_enabled=False
        pet.next_hunger=float('inf')
        for character in ('zenith','liberta','seir'):
            pet.set_character(character)
            pet.screen_area=QRect(0,0,1920,1080)
            pet.set_size(160,save=False)
            for mode in ('free','edge'):
                pet.set_roaming(mode,'clockwise',save=False)
                pet.enter_state('jump')
                assert pet.jump_cycles in (2,3)
                _,count,interval=pet.clip('jump')
                cycle=count*interval
                assert abs(pet.state_duration-pet.jump_cycles*cycle)<1e-9
                assert abs(pet.jump_cycle_duration-cycle)<1e-9
                for repeat in range(pet.jump_cycles):
                    pet.state_time=repeat*cycle+interval*.25
                    pet.update_frame(far)
                    key=pet.frame_key
                    frame_index=key[2] if mode=='edge' else key[1]
                    assert frame_index==0,(character,mode,repeat,key)
                    pet.state_time=repeat*cycle+(count-.25)*interval
                    pet.update_frame(far)
                    frame_index=pet.frame_key[2] if mode=='edge' else pet.frame_key[1]
                    assert frame_index==count-1,(character,mode,repeat,pet.frame_key)
                pet.state_time=pet.state_duration-.01
                with patch.object(pet,'choose_action') as choose:
                    pet.advance(.02,far)
                    choose.assert_called_once()
            pet.set_roaming('free','clockwise',save=False)
            pet.anchor_x=pet.x=960;pet.anchor_y=pet.y=950
            pet.next_gaze=float('inf');pet.gaze_elapsed=0
            for _ in range(5):
                pet.start_walk()
                floor=pet.y
                assert pet.target[1]==floor
                for _ in range(10):
                    pet.advance(.1,far)
                    assert abs(pet.y-floor)<1e-8,(character,pet.y,floor)
    print('PASS: 2-3 complete happy jumps per gesture for all characters in free/edge modes.')
    print('PASS: repeated free-roam left/right walks keep their starting height.')


if __name__=='__main__':main()
