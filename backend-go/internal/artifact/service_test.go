package artifact

import "testing"

func TestStudioIOMimeTypeAcceptsSupabaseStudioFormat(t *testing.T) {
	if got := mimeTypeFor("studio_io"); got != "application/x-studioformat" {
		t.Fatalf("studio_io MIME = %q, want application/x-studioformat", got)
	}
	for _, actual := range []string{
		"application/x-studioformat",
		"application/x-studioformat; charset=binary",
		"application/octet-stream",
	} {
		if !contentTypeMatches(actual, acceptableMimeTypesFor("studio_io")...) {
			t.Fatalf("studio_io content type %q should be accepted", actual)
		}
	}
	if contentTypeMatches("text/plain", acceptableMimeTypesFor("studio_io")...) {
		t.Fatal("studio_io must not accept text/plain")
	}
}

func TestLDrawMimeTypeRemainsPlainText(t *testing.T) {
	if got := mimeTypeFor("ldraw_ldr"); got != "text/plain" {
		t.Fatalf("ldraw_ldr MIME = %q, want text/plain", got)
	}
	if !contentTypeMatches("text/plain; charset=utf-8", acceptableMimeTypesFor("ldraw_mpd")...) {
		t.Fatal("ldraw_mpd should accept text/plain with parameters")
	}
	if contentTypeMatches("application/x-studioformat", acceptableMimeTypesFor("ldraw_ldr")...) {
		t.Fatal("ldraw_ldr must not accept Studio MIME")
	}
}
