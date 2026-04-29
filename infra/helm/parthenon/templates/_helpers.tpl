{{/*
infra/helm/parthenon/templates/_helpers.tpl
Shared template helpers for the Parthenon Helm chart.
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "parthenon.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this.
*/}}
{{- define "parthenon.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart label.
*/}}
{{- define "parthenon.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to every resource.
*/}}
{{- define "parthenon.labels" -}}
helm.sh/chart: {{ include "parthenon.chart" . }}
app.kubernetes.io/name: {{ include "parthenon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels — subset of labels used in matchLabels.
*/}}
{{- define "parthenon.selectorLabels" -}}
app.kubernetes.io/name: {{ include "parthenon.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Image registry helper — prepends global registry if set.
Usage: {{ include "parthenon.image" (dict "image" .Values.api.image "global" .Values.global) }}
*/}}
{{- define "parthenon.image" -}}
{{- $registry := .global.imageRegistry | default "" -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" (trimSuffix "/" $registry) .image.repository .image.tag -}}
{{- else -}}
{{- printf "%s:%s" .image.repository .image.tag -}}
{{- end -}}
{{- end }}

{{/*
Secret name.
*/}}
{{- define "parthenon.secretName" -}}
{{- printf "%s-secrets" (include "parthenon.fullname" .) }}
{{- end }}

{{/*
ConfigMap name.
*/}}
{{- define "parthenon.configMapName" -}}
{{- printf "%s-config" (include "parthenon.fullname" .) }}
{{- end }}
