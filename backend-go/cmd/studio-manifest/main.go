package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/partlibrary"
)

func main() {
	var studioRoot string
	var outDir string
	var legacyPartsFile string
	flag.StringVar(&studioRoot, "studio-root", "", "BrickLink Studio install root or its ldraw directory")
	flag.StringVar(&outDir, "out-dir", "", "output directory for manifest and reports")
	flag.StringVar(&legacyPartsFile, "legacy-parts-file", "", "optional newline/CSV/TSV file of legacy LDraw part numbers for coverage")
	flag.Parse()

	result, err := partlibrary.GenerateStudioManifest(partlibrary.Options{
		StudioRoot:      studioRoot,
		OutDir:          outDir,
		LegacyPartsFile: legacyPartsFile,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "studio-manifest: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("manifest: %s\n", result.ManifestPath)
	fmt.Printf("summary:  %s\n", result.SummaryPath)
	if result.CoveragePath != "" {
		fmt.Printf("coverage: %s\n", result.CoveragePath)
	}
	fmt.Printf("manifestSha256: %s\n", result.Manifest.ManifestSHA256)
	fmt.Printf("totalFiles: %d\n", result.Summary.TotalFiles)
	fmt.Printf("canonicalTopLevelParts: %d\n", result.Summary.TopLevelParts.CanonicalDistinctParts)
	fmt.Printf("officialTopLevelParts: %d\n", result.Summary.TopLevelParts.OfficialParts)
	fmt.Printf("unofficialTopLevelParts: %d\n", result.Summary.TopLevelParts.UnofficialParts)
	fmt.Printf("blPrefixedTopLevelParts: %d\n", result.Summary.TopLevelParts.BLPrefixedParts)
	if result.Summary.MetadataSources.ElementInfoListJSON != nil {
		fmt.Printf("elementInfoRows: %d\n", result.Summary.MetadataSources.ElementInfoListJSON.RowCount)
		fmt.Printf("elementInfoDistinctBLItemNos: %d\n", result.Summary.MetadataSources.ElementInfoListJSON.DistinctBLItemNos)
	}
}
