Files provided generated with:
```
python patch_bsp_files.py input_bsp/ default_stuff/ --output output_bsp/
```
Gives server operations an option to prevent any 'legit' sv_pure bypass (including my preloader) by patching whatever files you want (default_stuff in the example) to whatever bsp files you want. It will match the type of compression used by the map file in order to keep sizes relative, most likely LZMA or no compression at all.

I don't think it stops sound mod exploits but pretty much anything visual can be handled, the tradeoff is just the size of the map file.

This works because all lumps (besides the entities lump) are md5 verified upon joining a server. There is no way around this. This is how sv_pure is intended to work.