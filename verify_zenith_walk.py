"""Check that Zenith's walking soles stay on the standing floor."""
from PySide6.QtGui import QPainter, QPixmap, QRegion
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from character_resources import Character, discover_characters, load_art


def floor(sprite):
    return QRegion(sprite.mask()).boundingRect().bottom()


def main():
    app=QApplication.instance() or QApplication([])
    character=discover_characters()['zenith']
    old=Character(character.manifest,{**character.data,
                   'profile':{**character.profile,'align_walk_floor':False}})
    before=load_art(old); after=load_art(character)
    corrected=0
    for height in (64,160,320,400):
        before.resize(height); after.resize(height)
        target=floor(after.frames['idle'][0])
        for action in ('left','right'):
            for prior,aligned in zip(before.frames[action],after.frames[action]):
                delta=target-floor(prior)
                assert abs(delta)<=round(height*.04)+1,(height,action,delta)
                assert aligned.size()==prior.size()
                assert floor(aligned)==target,(height,action,delta)
                expected=QPixmap(prior.size()); expected.fill(Qt.GlobalColor.transparent)
                painter=QPainter(expected); painter.drawPixmap(0,delta,prior); painter.end()
                assert aligned.toImage()==expected.toImage()
                corrected+=bool(delta)
    assert corrected>0
    print(f'PASS: both Zenith walking directions at 64/160/320/400 px share the idle shoe floor; {corrected} corrected frames, original art preserved.')


if __name__=='__main__': main()
