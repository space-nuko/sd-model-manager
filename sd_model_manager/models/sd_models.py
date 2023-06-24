from sqlalchemy.orm import relationship, sessionmaker, declarative_base, Mapped, mapped_column
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric
from marshmallow import fields
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from .utils import JSON
import simplejson


Base = declarative_base()


class SDModel(Base):
    __tablename__ = "sd_model"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str]

    root_path = Column(String)
    filepath = Column(String)
    # preview_image = Column(LargeBinary, nullable=True)
    display_name = Column(String, nullable=True)
    author = Column(String, nullable=True)
    source = Column(String, nullable=True)
    keywords = Column(String, nullable=True)
    description = Column(String, nullable=True)
    rating = Column(Integer, nullable=True)
    tags = Column(String, nullable=True)

    __mapper_args__ = {
        "polymorphic_identity": "sd_model",
        "polymorphic_on": "type",
    }

    def __repr__(self):
        return f"{self.__class__.__name__}({self.filepath!r})"


class LoRAModel(SDModel):
    __tablename__ = "lora_model"

    id: Mapped[int] = mapped_column(ForeignKey("sd_model.id"), primary_key=True)

    __mapper_args__ = {
        "polymorphic_identity": "lora_model",
    }

    model_hash = Column(String, nullable=True)
    legacy_hash = Column(String, nullable=True)

    session_id = Column(Integer, nullable=True)
    training_started_at = Column(DateTime, nullable=True)
    output_name = Column(String, nullable=True)
    learning_rate = Column(Numeric, nullable=True)
    text_encoder_lr = Column(Numeric, nullable=True)
    unet_lr = Column(Numeric, nullable=True)
    num_train_images = Column(Integer, nullable=True)
    num_reg_images = Column(Integer, nullable=True)
    num_batches_per_epoch = Column(Integer, nullable=True)
    num_epochs = Column(Integer, nullable=True)
    epoch = Column(Integer, nullable=True)
    batch_size_per_device = Column(Integer, nullable=True)
    total_batch_size = Column(Integer, nullable=True)
    gradient_checkpointing = Column(Boolean, nullable=True)
    gradient_accumulation_steps = Column(Integer, nullable=True)
    max_train_steps = Column(Integer, nullable=True)
    lr_warmup_steps = Column(Integer, nullable=True)
    lr_scheduler = Column(String, nullable=True)
    network_module = Column(String, nullable=True)
    network_dim = Column(Integer, nullable=True)
    network_alpha = Column(Numeric, nullable=True)
    mixed_precision = Column(Boolean, nullable=True)
    full_fp16 = Column(Boolean, nullable=True)
    v2 = Column(Boolean, nullable=True)
    resolution = Column(String, nullable=True)
    clip_skip = Column(Integer, nullable=True)
    max_token_length = Column(Integer, nullable=True)
    color_aug = Column(Boolean, nullable=True)
    flip_aug = Column(Boolean, nullable=True)
    random_crop = Column(Boolean, nullable=True)
    shuffle_caption = Column(Boolean, nullable=True)
    cache_latents = Column(Boolean, nullable=True)
    enable_bucket = Column(Boolean, nullable=True)
    min_bucket_reso = Column(Integer, nullable=True)
    max_bucket_reso = Column(Integer, nullable=True)
    seed = Column(Integer, nullable=True)
    keep_tokens = Column(Boolean, nullable=True)
    noise_offset = Column(Numeric, nullable=True)
    dataset_dirs = Column(JSON, nullable=True)
    reg_dataset_dirs = Column(JSON, nullable=True)
    tag_frequency = Column(JSON, nullable=True)
    sd_model_name = Column(String, nullable=True)
    sd_model_hash = Column(String, nullable=True)
    sd_new_model_hash = Column(String, nullable=True)
    sd_vae_name = Column(String, nullable=True)
    sd_vae_hash = Column(String, nullable=True)
    sd_new_vae_hash = Column(String, nullable=True)
    vae_name = Column(String, nullable=True)
    training_comment = Column(String, nullable=True)
    bucket_info = Column(JSON, nullable=True)
    sd_scripts_commit_hash = Column(String, nullable=True)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.filepath!r})"


class LoRAModelSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = LoRAModel
        render_module = simplejson
        include_fk = True
        load_instance = False

    dataset_dirs = fields.Raw()
    reg_dataset_dirs = fields.Raw()
    tag_frequency = fields.Raw()
    bucket_info = fields.Raw()
