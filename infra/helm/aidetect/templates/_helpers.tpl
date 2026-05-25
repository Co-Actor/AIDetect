{{/* Expand the name of the chart. */}}
{{- define "aidetect.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Full release name. */}}
{{- define "aidetect.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/* Common labels (merged with commonLabels from values). */}}
{{- define "aidetect.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{/* Service-level labels (component-specific). */}}
{{- define "aidetect.componentLabels" -}}
{{- $component := .component -}}
{{- $top := .top -}}
app.kubernetes.io/name: {{ printf "aidetect-%s" $component }}
app.kubernetes.io/component: {{ $component }}
{{ include "aidetect.labels" $top }}
{{- end -}}

{{/* Resolved image reference for a component. */}}
{{- define "aidetect.image" -}}
{{- $repo := .image.repository -}}
{{- $tag := default .top.Values.image.tag .image.tag -}}
{{- printf "%s/%s:%s" .top.Values.image.registry $repo $tag -}}
{{- end -}}
