
all: force_reuseport.so

force_reuseport.so: force_reuseport.c
	$(CC) -Wall -shared -fPIC -o $@ $< -ldl

clean:
	rm -f force_reuseport.so

.PHONY: all clean
