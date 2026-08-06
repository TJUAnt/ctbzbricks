package apierror

import (
	"net/http"
	"regexp"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/requestmeta"
	"github.com/gin-gonic/gin"
)

var machineCodePattern = regexp.MustCompile(`^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$`)

type Error struct {
	Code       string
	Params     map[string]any
	HTTPStatus int
}

type Response struct {
	Error Detail `json:"error"`
}

type Detail struct {
	Code    string         `json:"code"`
	Params  map[string]any `json:"params"`
	TraceID string         `json:"traceId"`
}

func New(code string, httpStatus int, params map[string]any) *Error {
	if !machineCodePattern.MatchString(code) {
		panic("invalid machine error code")
	}
	if httpStatus < 400 || httpStatus > 599 {
		panic("invalid HTTP error status")
	}
	if params == nil {
		params = map[string]any{}
	}
	return &Error{Code: code, Params: params, HTTPStatus: httpStatus}
}

func Write(c *gin.Context, apiErr *Error) {
	c.AbortWithStatusJSON(apiErr.HTTPStatus, Response{Error: Detail{
		Code:    apiErr.Code,
		Params:  apiErr.Params,
		TraceID: requestmeta.FromGin(c),
	}})
}

func WriteInternal(c *gin.Context) {
	Write(c, New("common.internal_error", http.StatusInternalServerError, nil))
}
