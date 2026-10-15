"""Optional display-time resampling of the original sprites, with fixed geometry.

No generated artwork or modified resource files. Alpha is resampled in premultiplied
space; the original 0/32/128 coverage bands retain contact points and hit testing.
"""
from collections import OrderedDict
from PIL import Image, ImageChops, ImageFilter
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

QUALITY_PROFILE='clarity-v1'
CACHE_LIMIT=64*1024*1024
_cache=OrderedDict()
_cache_bytes=0


def clear_cache():
    global _cache_bytes
    _cache.clear(); _cache_bytes=0


def _image(pixmap):
    image=pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombytes('RGBA',(image.width(),image.height()),bytes(image.constBits()),
                           'raw','RGBA',image.bytesPerLine())


def _coverage(alpha,reference):
    # Foot alignment uses alpha>=128, corner contacts alpha>=32, and native
    # windows need zero-alpha pixels to remain transparent. Keep all three.
    result=Image.new('L',alpha.size)
    for low,high in ((1,31),(32,127),(128,254),(255,255)):
        mask=reference.point(lambda a:255 if low<=a<=high else 0)
        bounded=alpha.point(lambda a:max(low,min(high,a)))
        result.paste(bounded,mask=mask)
    return result


def _detail(image):
    # A small luminance-only change sharpens existing lines without changing
    # their hue or inventing details. Exclude transparent edges from sharpening.
    rgb=image.convert('RGB'); alpha=image.getchannel('A')
    luminance=rgb.convert('L')
    blurred=luminance.filter(ImageFilter.GaussianBlur(.65))
    delta=ImageChops.subtract(luminance,blurred,offset=128)
    delta=delta.point(lambda v:128+max(-4,min(4,round((v-128)*.22))))
    channels=[ImageChops.add(channel,delta,offset=-128) for channel in rgb.split()]
    sharpened=Image.merge('RGB',channels)
    interior=alpha.filter(ImageFilter.MinFilter(3)).point(lambda a:255 if a>=224 else 0)
    result=Image.composite(sharpened,rgb,interior).convert('RGBA')
    result.putalpha(alpha)
    return result


def scale_sprite(source,height,character):
    """Same Qt canvas dimensions and contact coverage, higher quality color sampling."""
    global _cache_bytes
    height=max(1,round(height))
    if character.profile.get('render_quality')!=QUALITY_PROFILE:
        return source.scaledToHeight(height,Qt.TransformationMode.SmoothTransformation)
    key=(source.cacheKey(),height,QUALITY_PROFILE)
    if key in _cache:
        _cache.move_to_end(key)
        return QPixmap(_cache[key])
    original=source.scaledToHeight(height,Qt.TransformationMode.SmoothTransformation)
    reference=_image(original)
    # Pillow resamples RGBA as premultiplied RGBa, avoiding dark edge halos.
    resized=_image(source).resize(reference.size,Image.Resampling.LANCZOS)
    result=_detail(resized)
    result.putalpha(_coverage(result.getchannel('A'),reference.getchannel('A')))
    raw=result.tobytes()
    image=QImage(raw,result.width,result.height,result.width*4,QImage.Format.Format_RGBA8888).copy()
    pixmap=QPixmap.fromImage(image)
    cost=pixmap.width()*pixmap.height()*4
    while _cache and _cache_bytes+cost>CACHE_LIMIT:
        _,old=_cache.popitem(last=False); _cache_bytes-=old.width()*old.height()*4
    if cost<=CACHE_LIMIT:
        _cache[key]=pixmap; _cache_bytes+=cost
    return QPixmap(pixmap)
