import cv2
with cv2.QRCodeDetector() as d:
 d.detectAndDecodeMulti(img)
