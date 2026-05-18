{%- if salt['pillar.get']('prometheus:saline_enabled', False) %}
{%- if salt['pillar.get']('prometheus:saline_https_connection', True) %}
  {% set saline_port = 443 %}
{%- else %}
  {% set saline_port = 80 %}
{%- endif %}
saline-prometheus-cfg:
  file.managed:
  - name: /etc/prometheus/saline.yml
  - contents: |
      - targets:
        - {{ salt['pillar.get']('mgr_origin_server') }}:{{ saline_port }}
        labels:
          __metrics_path__: {{ salt['pillar.get']('prometheus:saline_metrics_path') }}
{%- if salt['pillar.get']('prometheus:saline_https_connection', False) %}
          __scheme__: https
{% endif %}
  - require_in:
    - file: config_file
{%- else %}
saline-prometheus-cfg:
  file.absent:
  - name: /etc/prometheus/saline.yml
{%- endif %}
