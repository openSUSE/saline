saline-prometheus-cfg:
  file.managed:
  - name: /etc/prometheus/saline.yml
  - contents: |
      - targets:
        - {{ salt['pillar.get']('mgr_origin_server') }}
        labels:
          __metrics_path__: /saline/metrics
          __scheme__: https
  - require_in:
    - file: config_file
