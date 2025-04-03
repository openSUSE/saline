{%- if salt['pillar.get']('prometheus:saline_enabled', False) %}
saline-prometheus-cfg:
  file.managed:
  - name: /etc/prometheus/saline.yml
  - contents: |
      - targets:
        - {{ salt['pillar.get']('mgr_server') }}
        labels:
          __metrics_path__: /saline/metrics
{%- if salt['pillar.get']('prometheus:saline_https_connection', False) %}
          __scheme__: https
{% endif %}
  - require_in:
    - file: config_file
{%- endif %}
