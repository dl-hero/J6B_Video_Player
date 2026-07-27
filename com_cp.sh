#!/bin/bash

cd src/
make clean && make && cp venc_stream ../bin/
cd ..
scp bin/venc_stream root@192.168.0.140:/app/sample/S83_Sample/S83E04_Module/venc_stream/bin/
sync
sync
sync
echo "make and scp done"

