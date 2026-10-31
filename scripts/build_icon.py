"""Render the editable vector mark into a multi-resolution Windows icon."""
from pathlib import Path
import struct
from PySide6.QtCore import QBuffer,QIODevice,Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtSvg import QSvgRenderer
root=Path(__file__).resolve().parents[1]
renderer=QSvgRenderer(str(root/'web/investlab-icon.svg'))
sizes=[16,24,32,48,64,128,256]
images=[]
for size in sizes:
    image=QImage(size,size,QImage.Format_ARGB32);image.fill(Qt.transparent)
    painter=QPainter(image);renderer.render(painter);painter.end()
    buf=QBuffer();buf.open(QIODevice.WriteOnly);image.save(buf,'PNG');images.append(bytes(buf.data()))
offset=6+16*len(sizes);entries=[]
for size,data in zip(sizes,images):
    entries.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(data),offset));offset+=len(data)
(root/'web/investlab.ico').write_bytes(struct.pack('<HHH',0,1,len(sizes))+b''.join(entries)+b''.join(images))
image.save(str(root/'web/investlab-icon.png'))
