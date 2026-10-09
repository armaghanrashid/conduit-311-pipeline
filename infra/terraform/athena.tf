resource "aws_athena_workgroup" "conduit" {
  name        = "${var.name_prefix}-311"
  description = "Queries over the conduit lake, with results kept in the lake bucket."
  state       = "ENABLED"

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.athena_scan_limit_bytes

    result_configuration {
      output_location = "s3://${aws_s3_bucket.lake.id}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
