# Release Process

Guidelines for releasing new versions of Amebo.

## Versioning

Amebo follows [Semantic Versioning](https://semver.org/):
- **MAJOR**: Breaking changes
- **MINOR**: New features (backward compatible)
- **PATCH**: Bug fixes (backward compatible)

## Release Checklist

### Pre-Release
- [ ] All tests passing
- [ ] Documentation updated
- [ ] CHANGELOG.md updated
- [ ] Version bumped in setup.py
- [ ] Security review completed

### Release
- [ ] Create release tag
- [ ] Build and publish Docker image
- [ ] Publish to PyPI
- [ ] Update GitHub release notes
- [ ] Deploy to staging
- [ ] Deploy to production

### Post-Release
- [ ] Monitor for issues
- [ ] Update documentation site
- [ ] Announce release
- [ ] Plan next release

## Release Commands

```bash
# Create release tag
git tag -a v1.2.3 -m "Release v1.2.3"
git push origin v1.2.3

# Build Docker image
docker build -t rayattack/amebo:v1.2.3 .
docker push rayattack/amebo:v1.2.3

# Publish to PyPI
python setup.py sdist bdist_wheel
twine upload dist/*
```

## Hotfix Process

For critical bug fixes:
1. Create hotfix branch from main
2. Apply minimal fix
3. Test thoroughly
4. Release patch version
5. Merge back to main

## Next Steps
- [Contributing Guide](contributing.md)
- [Testing Guide](testing.md)
