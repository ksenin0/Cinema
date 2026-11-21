"""Administrator-only report and export endpoint."""

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import ReportPermission
from reports.exports import export_csv, export_pdf, export_xlsx
from reports.services import build_report


class ReportRangeSerializer(serializers.Serializer):
    """Inclusive local-date reporting range."""

    start = serializers.DateField()
    end = serializers.DateField()

    def validate(self, attrs: dict) -> dict:
        """Reject reversed date ranges and excessively large synchronous reports."""
        if attrs["end"] < attrs["start"] or (attrs["end"] - attrs["start"]).days > 366:
            raise serializers.ValidationError("Период должен составлять от 1 до 367 дней.")
        return attrs


class ReportView(APIView):
    """Revenue and attendance as JSON, CSV, XLSX or PDF."""

    permission_classes = [ReportPermission]

    def get(self, request: Request) -> Response | HttpResponse:
        """Validate the date range and return report data in the requested representation."""
        serializer = ReportRangeSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        report = build_report(**serializer.validated_data)
        export_format = request.query_params.get("export")
        if not export_format:
            return Response(report)
        exporters = {
            "csv": (export_csv, "text/csv; charset=utf-8"),
            "xlsx": (
                export_xlsx,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "pdf": (export_pdf, "application/pdf"),
        }
        if export_format not in exporters:
            raise serializers.ValidationError({"export": "Допустимы csv, xlsx, pdf."})
        exporter, content_type = exporters[export_format]
        response = HttpResponse(exporter(report), content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="cinema-report.{export_format}"'
        response["Cache-Control"] = "no-store"
        return response
