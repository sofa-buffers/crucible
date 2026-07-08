module crucible/driver/go

go 1.21

require github.com/sofa-buffers/corelib-go v0.0.0

// Resolved locally from the vendored corelib (scripts/bootstrap.sh populates it).
replace github.com/sofa-buffers/corelib-go => ../../vendor/corelib-go
