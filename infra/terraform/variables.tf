variable "aws_region" {
  description = "Region for every resource."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for resource names. Lowercase letters, digits and hyphens."
  type        = string
  default     = "conduit"
}

variable "lake_bucket_name" {
  description = "Globally unique name of the S3 bucket that holds every layer."
  type        = string
  default     = "conduit-311-lake-example"
}

variable "image_tag" {
  description = "Tag of the container image in ECR that the scheduled task runs."
  type        = string
  default     = "0.1.0"
}

variable "schedule_expression" {
  description = "EventBridge schedule for the nightly run."
  type        = string
  default     = "cron(0 6 * * ? *)"
}

variable "subnet_ids" {
  description = "Subnets for the Fargate task. Supply them at apply time."
  type        = list(string)
  default     = []
}

variable "security_group_ids" {
  description = "Security groups for the Fargate task. Supply them at apply time."
  type        = list(string)
  default     = []
}

variable "assign_public_ip" {
  description = "Give the task a public IP so it can reach the API from a public subnet."
  type        = bool
  default     = false
}

variable "task_cpu" {
  description = "Fargate CPU units."
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "Fargate memory in MiB."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  description = "Retention of the task log group."
  type        = number
  default     = 30
}

variable "athena_scan_limit_bytes" {
  description = "Per-query data-scanned cutoff for the Athena workgroup."
  type        = number
  default     = 10737418240
}
