{{- $progressive := .Values.progressiveDelivery | default dict -}}
{{- if $progressive.enabled }}
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: frontend
  namespace: {{ .Release.Namespace }}
  labels:
    app.kubernetes.io/name: frontend
    app.kubernetes.io/part-of: boutique
spec:
  replicas: {{ .Values.frontend.replicaCount }}
  revisionHistoryLimit: 3
  minReadySeconds: 5
  progressDeadlineSeconds: 300
  progressDeadlineAbort: true
  selector:
    matchLabels:
      app.kubernetes.io/name: frontend
  workloadRef:
    apiVersion: apps/v1
    kind: Deployment
    name: frontend
    scaleDown: onsuccess
  strategy:
    blueGreen:
      activeService: frontend
      previewService: frontend-preview
      autoPromotionEnabled: true
      scaleDownDelaySeconds: 600
      scaleDownDelayRevisionLimit: 1
      abortScaleDownDelaySeconds: 30
      prePromotionAnalysis:
        templates:
        - templateName: frontend-preview-check
        args:
        - name: service-name
          value: frontend-preview
      postPromotionAnalysis:
        templates:
        - templateName: frontend-serving-check
        args:
        - name: service-name
          value: frontend
---
apiVersion: v1
kind: Service
metadata:
  name: frontend-preview
  namespace: {{ .Release.Namespace }}
spec:
  selector:
    app.kubernetes.io/name: frontend
  ports:
  - name: http
    port: 8080
    targetPort: http
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: frontend-rollout-analysis
  namespace: {{ .Release.Namespace }}
automountServiceAccountToken: false
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: frontend-rollout-analysis
  namespace: {{ .Release.Namespace }}
data:
  checkout-check.mjs: |
{{ .Files.Get "analysis/checkout-check.mjs" | indent 4 }}
{{- range $phase := list "preview" "serving" }}
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: frontend-{{ $phase }}-check
  namespace: {{ $.Release.Namespace }}
spec:
  args:
  - name: service-name
  metrics:
  - name: dependencies-ready
    interval: 10s
    count: {{ if eq $phase "preview" }}3{{ else }}12{{ end }}
    failureLimit: 1
    consecutiveErrorLimit: 1
    successCondition: result.status == 'ok'
    provider:
      web:
        url: {{ printf "http://{{args.service-name}}.%s.svc.cluster.local:8080/health/ready" $.Release.Namespace | quote }}
        timeoutSeconds: 5
  - name: functional-checkout
    interval: 30s
    count: {{ if eq $phase "preview" }}1{{ else }}3{{ end }}
    failureLimit: 0
    consecutiveErrorLimit: 1
    provider:
      job:
        spec:
          backoffLimit: 0
          activeDeadlineSeconds: 90
          ttlSecondsAfterFinished: 3600
          template:
            metadata:
              labels:
                app.kubernetes.io/name: frontend-rollout-analysis
            spec:
              serviceAccountName: frontend-rollout-analysis
              automountServiceAccountToken: false
              restartPolicy: Never
              imagePullSecrets:
              - name: ghcr-pull
              securityContext:
                runAsNonRoot: true
                runAsUser: 1000
                runAsGroup: 1000
              containers:
              - name: checkout
                image: ghcr.io/subhankar12-spec/boutique-frontend@sha256:719736fb72cf4aac5131630374ab44fcd1aa7a365250bfbf40caacda4cca25aa
                command: [node, /analysis/checkout-check.mjs]
                env:
                - name: BASE_URL
                  value: {{ printf "http://{{args.service-name}}.%s.svc.cluster.local:8080" $.Release.Namespace | quote }}
                - name: PUBLIC_ORIGIN
                  value: {{- range (index $.Values.frontend.deployment.template.spec.containers 0).env }}{{ if eq .name "PUBLIC_ORIGIN" }} {{ .value | quote }}{{ end }}{{- end }}
                resources:
                  requests: {cpu: 25m, memory: 32Mi}
                  limits: {cpu: 250m, memory: 96Mi}
                securityContext:
                  allowPrivilegeEscalation: false
                  readOnlyRootFilesystem: true
                  capabilities:
                    drop: [ALL]
                  seccompProfile:
                    type: RuntimeDefault
                volumeMounts:
                - name: analysis
                  mountPath: /analysis
                  readOnly: true
              volumes:
              - name: analysis
                configMap:
                  name: frontend-rollout-analysis
  - name: browse-products
    interval: 10s
    count: {{ if eq $phase "preview" }}3{{ else }}12{{ end }}
    failureLimit: 1
    consecutiveErrorLimit: 1
    successCondition: len(result) > 0 && result[0].id != '' && result[0].price > 0
    provider:
      web:
        url: {{ printf "http://{{args.service-name}}.%s.svc.cluster.local:8080/api/products" $.Release.Namespace | quote }}
        timeoutSeconds: 5
{{- end }}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frontend-progressive-checks
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: frontend
  policyTypes: [Ingress]
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: argo-rollouts
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: frontend-rollout-analysis
    ports:
    - protocol: TCP
      port: 8080
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: progressive-controller
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: argo-rollouts
  policyTypes: [Ingress, Egress]
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - protocol: TCP
      port: 8090
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  - to:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: frontend
    ports:
    - protocol: TCP
      port: 8080
  - to:
    - ipBlock:
        cidr: {{ required "progressiveDelivery.apiServerCIDR must identify the Kubernetes API endpoint" $progressive.apiServerCIDR | quote }}
    ports:
    - protocol: TCP
      port: 6443
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frontend-rollout-analysis
  namespace: {{ .Release.Namespace }}
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: frontend-rollout-analysis
  policyTypes: [Ingress, Egress]
  ingress: []
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  - to:
    - podSelector:
        matchLabels:
          app.kubernetes.io/name: frontend
    ports:
    - protocol: TCP
      port: 8080
{{- end }}
