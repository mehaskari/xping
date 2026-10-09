# COPR "make_srpm" build: COPR runs `make -f .copr/Makefile srpm outdir=... spec=...`
# in a fresh checkout. Builds the sdist from this checkout and a source RPM
# from packaging/fedora/xping.spec, with the version taken from pyproject.toml,
# so every push or tag builds the code it points at.
SPEC := packaging/fedora/xping.spec

srpm:
	dnf -y install python3-build python3-setuptools rpm-build
	VERSION=$$(python3 -c "import re; print(re.search(r'(?m)^version = \"(.+?)\"', open('pyproject.toml').read()).group(1))") && \
	python3 -m build --sdist --outdir "$(outdir)" . && \
	sed "s/^Version:.*/Version:        $$VERSION/" $(SPEC) > "$(outdir)/xping.spec" && \
	rpmbuild -bs "$(outdir)/xping.spec" \
	    --define "_sourcedir $(outdir)" --define "_srcrpmdir $(outdir)"
